from __future__ import annotations

import asyncio
import logging
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
from common.logging import WORKER_TASK_LOG_FILES, log_component, setup_logging

COMMAND_POLL_INTERVAL_SECONDS = 2
COMMAND_DRAIN_LIMIT = 25

logger = logging.getLogger("bot_worker")


async def drain_bot_commands(session, settings) -> None:
    """Claim and execute pending bot commands within the caller's transaction."""
    commands = await process_pending_bot_commands(
        session,
        settings=settings,
        limit=getattr(settings.bot, "command_drain_limit", COMMAND_DRAIN_LIMIT),
    )
    for command in commands:
        typer.echo(f"bot_command: {command.id} {command.command_type} {command.status}")


async def run_pipeline_tick(session, settings) -> None:
    """Run a scheduled pipeline pass plus pending investigations in one transaction."""
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
    # (see _pipeline_loop) so their external sends / state are not rolled back.


async def _command_loop(session_factory, settings, *, shutdown) -> None:
    """Drain pending bot commands on a fixed cadence in their own transaction.

    Runs independently of :func:`_pipeline_loop` so user commands stay responsive while
    a long pipeline tick is in flight. No command can trigger the pipeline, so the two
    loops never run the pipeline concurrently.
    """
    # Tag this task so every record it emits is routed to worker-command.log.
    log_component.set("command")
    poll_interval = getattr(
        settings.bot, "command_poll_interval_seconds", COMMAND_POLL_INTERVAL_SECONDS
    )
    while not shutdown.is_set():
        try:
            await _with_session(
                lambda session: drain_bot_commands(session, settings),
                settings=settings,
                session_factory=session_factory,
            )
        except Exception as exc:  # noqa: BLE001 - a failed drain must not kill the worker
            await _record_failed_job(session_factory, "bot_command", exc)
            logger.exception("bot command drain failed: %s", exc)
        with suppress(TimeoutError):
            await asyncio.wait_for(shutdown.wait(), timeout=poll_interval)


async def _pipeline_loop(session_factory, settings, *, shutdown) -> None:
    """Run the scheduled pipeline and post-commit deliveries on the polling interval."""
    # Tag this task so every record it emits is routed to worker-pipeline.log.
    log_component.set("pipeline")
    running_loop = asyncio.get_running_loop()
    interval = settings.bot.polling_interval_seconds
    last_pipeline_run_at = running_loop.time()
    while not shutdown.is_set():
        wait_remaining = last_pipeline_run_at + interval - running_loop.time()
        if wait_remaining > 0:
            with suppress(TimeoutError):
                await asyncio.wait_for(shutdown.wait(), timeout=wait_remaining)
            continue
        last_pipeline_run_at = running_loop.time()
        try:
            await _with_session(
                lambda session: run_pipeline_tick(session, settings),
                settings=settings,
                session_factory=session_factory,
            )
        except Exception as exc:  # noqa: BLE001 - a failed tick must not kill the worker
            await _record_failed_job(session_factory, "pipeline", exc)
            logger.exception("pipeline tick failed: %s", exc)
        else:
            delivery_config = AlertDeliveryConfig.from_settings(settings)
            if delivery_config.channel == "telegram":
                with suppress(Exception):
                    await deliver_pending_alerts(session_factory, delivery_config)
            with suppress(Exception):
                await maybe_send_daily_digest(session_factory, settings)
            with suppress(Exception):
                await run_operational_checks_in_transaction(session_factory, settings)


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
        # Reconfigure logging for the worker process: the pipeline and command
        # tasks each get their own file, lifecycle records go to worker.log.
        setup_logging(settings, component="worker")
        logger.info("worker started; jobs=%s", ", ".join(jobs))
        session_factory = make_session_factory(settings)
        shutdown = asyncio.Event()
        running_loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            with suppress(NotImplementedError, RuntimeError):
                running_loop.add_signal_handler(sig, shutdown.set)
        # Command processing and the scheduled pipeline run on independent loops so a
        # long pipeline tick never blocks command responsiveness. The pipeline runs only
        # here, so the two never ingest/cluster concurrently.
        tasks = [
            asyncio.create_task(
                _command_loop(session_factory, settings, shutdown=shutdown)
            ),
            asyncio.create_task(
                _pipeline_loop(session_factory, settings, shutdown=shutdown)
            ),
        ]
        try:
            await shutdown.wait()
        finally:
            # Let each loop finish its current cycle, then exit on the shared event.
            shutdown.set()
            await asyncio.gather(*tasks, return_exceptions=True)
            logger.info("worker stopped")

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
def worker_logs(
    tail: Annotated[int, typer.Option("--tail")] = 200,
    component: Annotated[
        str, typer.Option("--component", help="pipeline | command | worker")
    ] = "pipeline",
) -> None:
    """Retrieve recent runtime log lines for a worker component."""
    filenames = {**WORKER_TASK_LOG_FILES, "worker": "worker.log"}
    filename = filenames.get(component)
    if filename is None:
        choices = ", ".join(filenames)
        typer.echo(f"unknown component '{component}'; choose one of: {choices}")
        raise typer.Exit(1)
    settings = _settings()
    if not settings.logging.log_dir:
        typer.echo("file logging is disabled (logging.log_dir is unset)")
        return
    log_path = Path(settings.logging.log_dir) / filename
    if not log_path.exists():
        typer.echo(f"worker logs are stdout/stderr; {log_path} not found")
        return
    lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
    for line in lines[-tail:]:
        typer.echo(line)
@worker_app.command("health")
def worker_health() -> None:
    """Check health status of the worker and active database session."""
    from bot_worker.cli.health import health_pipeline

    health_pipeline()
