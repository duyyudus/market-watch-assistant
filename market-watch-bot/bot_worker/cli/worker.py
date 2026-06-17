from __future__ import annotations

import asyncio
import signal
from contextlib import suppress
from datetime import UTC, datetime, time, timedelta
from pathlib import Path
from typing import Annotated
from zoneinfo import ZoneInfo

import typer
from sqlalchemy import select

from bot_worker.cli.apps import worker_app
from bot_worker.cli.common import _echo_json, _record_failed_job, _run, _settings, _with_session
from bot_worker.db.models import DigestRecord, JobRun
from bot_worker.db.session import make_session_factory
from bot_worker.embeddings import EmbeddingConfig
from bot_worker.investigation import InvestigationConfig
from bot_worker.services import (
    CORE_JOBS,
    AlertDeliveryConfig,
    deliver_pending_alerts,
    record_job_run,
    run_pending_investigations,
    run_pipeline,
)
from bot_worker.services.bot_commands import process_pending_bot_commands
from bot_worker.services.digests import build_digest_record, send_digest_record
from bot_worker.services.operations import run_operational_checks
from common.llm import LLMConfig

COMMAND_POLL_INTERVAL_SECONDS = 2
COMMAND_DRAIN_LIMIT = 25


async def run_worker_tick(
    session,
    settings,
    *,
    last_pipeline_run_at: float,
    now: float,
) -> float:
    commands = await process_pending_bot_commands(
        session,
        settings=settings,
        limit=getattr(settings.bot, "command_drain_limit", 25),
    )
    for command in commands:
        typer.echo(f"bot_command: {command.id} {command.command_type} {command.status}")
    if now - last_pipeline_run_at < settings.bot.polling_interval_seconds:
        return last_pipeline_run_at

    result = await run_pipeline(
        session,
        freshness_hours=settings.ingestion.rss_freshness_hours,
        embedding_config=EmbeddingConfig.from_settings(settings),
        llm_config=LLMConfig.from_settings(settings),
        investigation_config=InvestigationConfig.from_settings(settings),
        alert_delivery_config=AlertDeliveryConfig.from_settings(settings),
        tracking_params=getattr(settings.ingestion, "tracking_params", None),
        disclosure_noise_patterns=getattr(
            settings.ingestion, "disclosure_noise_patterns", None
        ),
    )
    await record_job_run(session, "pipeline", result)
    typer.echo(f"pipeline: {result}")
    investigation_config = InvestigationConfig.from_settings(settings)
    if investigation_config.enabled:
        pending_result = await run_pending_investigations(
            session,
            config=investigation_config,
            llm_config=LLMConfig.from_settings(settings),
            limit=investigation_config.max_concurrency,
        )
        await record_job_run(session, "agent_investigation", pending_result)
        typer.echo(f"agent_investigation: {pending_result}")
    # Digest delivery and operational checks run after this transaction commits
    # (see the worker loop) so their external sends / state are not rolled back.
    return now


async def maybe_send_daily_digest(session_factory, settings) -> None:
    """Build and deliver the daily digest outside the pipeline transaction.

    The digest record is committed (status ``built``) before delivery, and ``sent_at``
    is committed immediately after a successful send, so a crash cannot roll back a
    sent digest and cause it to be re-delivered on the next tick. A built-but-unsent
    digest (crash before send) is retried instead of rebuilt.
    """
    timezone = ZoneInfo(getattr(settings.bot, "timezone", "Asia/Bangkok"))
    local_now = datetime.now(timezone)
    if local_now.time() < time(8, 0):
        return
    window_end = local_now.replace(hour=8, minute=0, second=0, microsecond=0)
    window_start = window_end - timedelta(hours=24)
    window_end_utc = window_end.astimezone(UTC)
    config = AlertDeliveryConfig.from_settings(settings)

    async with session_factory() as session, session.begin():
        existing = await session.scalar(
            select(DigestRecord)
            .where(DigestRecord.digest_type == "daily")
            .where(DigestRecord.window_end == window_end_utc)
            .limit(1)
        )
        if existing is not None and existing.sent_at is not None:
            return
        if existing is None:
            digest = await build_digest_record(
                session,
                since=window_start.astimezone(UTC),
                until=window_end_utc,
                threshold=settings.alerts.digest_threshold,
                config=LLMConfig.from_settings(settings),
            )
        else:
            digest = existing
        digest_id = digest.id

    async with session_factory() as session, session.begin():
        digest = await session.get(DigestRecord, digest_id)
        if digest is None or digest.sent_at is not None:
            return
        await send_digest_record(session, digest, config)


async def run_operational_checks_in_transaction(session_factory, settings) -> None:
    config = AlertDeliveryConfig.from_settings(settings, channel="telegram")
    async with session_factory() as session, session.begin():
        await run_operational_checks(
            session,
            settings=settings,
            alert_delivery_config=config,
        )


@worker_app.command("start")
def worker_start(only: Annotated[str | None, typer.Option("--only")] = None) -> None:
    """Start the background worker process to run pipeline jobs at configured intervals."""
    jobs = only.split(",") if only else CORE_JOBS
    typer.echo(f"Starting worker loop for jobs: {', '.join(jobs)}")
    typer.echo("Use Ctrl+C to stop")

    async def loop() -> None:
        settings = _settings()
        session_factory = make_session_factory(settings)
        shutdown = asyncio.Event()
        running_loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            with suppress(NotImplementedError, RuntimeError):
                running_loop.add_signal_handler(sig, shutdown.set)
        last_pipeline_run_at = asyncio.get_running_loop().time()
        while not shutdown.is_set():
            now = asyncio.get_running_loop().time()
            ran_pipeline = now - last_pipeline_run_at >= settings.bot.polling_interval_seconds

            async def action(
                session,
                settings=settings,
                last_pipeline_run_at=last_pipeline_run_at,
                now=now,
            ):
                return await run_worker_tick(
                    session,
                    settings,
                    last_pipeline_run_at=last_pipeline_run_at,
                    now=now,
                )

            try:
                last_pipeline_run_at = await _with_session(
                    action,
                    settings=settings,
                    session_factory=session_factory,
                )
            except Exception as exc:  # noqa: BLE001 - a failed tick must not kill the worker
                await _record_failed_job(session_factory, "pipeline", exc)
                typer.echo(f"pipeline tick failed: {exc}")
                # Back off until the next interval instead of hammering a broken run.
                last_pipeline_run_at = now
            else:
                if ran_pipeline:
                    delivery_config = AlertDeliveryConfig.from_settings(settings)
                    if delivery_config.channel == "telegram":
                        with suppress(Exception):
                            await deliver_pending_alerts(session_factory, delivery_config)
                    with suppress(Exception):
                        await maybe_send_daily_digest(session_factory, settings)
                    with suppress(Exception):
                        await run_operational_checks_in_transaction(session_factory, settings)
            try:
                await asyncio.wait_for(
                    shutdown.wait(),
                    timeout=getattr(settings.bot, "command_poll_interval_seconds", 2),
                )
            except TimeoutError:
                continue

    _run(loop())
@worker_app.command("status")
def worker_status() -> None:
    """Show worker status from recent job activity."""
    async def action(session):
        latest = await session.scalar(select(JobRun).order_by(JobRun.started_at.desc()).limit(1))
        _echo_json(
            {
                "mode": "foreground_or_process_manager",
                "supervisor_state_recorded": False,
                "latest_job": (
                    {
                        "id": latest.id,
                        "job_name": latest.job_name,
                        "status": latest.status,
                        "started_at": latest.started_at,
                        "completed_at": latest.completed_at,
                        "error": latest.error_message,
                    }
                    if latest is not None
                    else None
                ),
            }
        )

    _run(_with_session(action))


@worker_app.command("logs")
def worker_logs(tail: Annotated[int, typer.Option("--tail")] = 200) -> None:
    """Retrieve recent runtime log lines when the configured log file exists."""
    log_path = Path(".log/market-watch-bot.log")
    if not log_path.exists():
        typer.echo("worker logs are stdout/stderr; .log/market-watch-bot.log not found")
        return
    lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
    for line in lines[-tail:]:
        typer.echo(line)
@worker_app.command("health")
def worker_health() -> None:
    """Check health status of the worker and active database session."""
    from bot_worker.cli.health import health_pipeline

    health_pipeline()
