from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Annotated

import typer
from sqlalchemy import select

from bot_worker.cli.apps import worker_app
from bot_worker.cli.common import _echo_json, _run, _settings, _with_session
from bot_worker.db.models import JobRun
from bot_worker.embeddings import EmbeddingConfig
from bot_worker.investigation import InvestigationConfig
from bot_worker.llm import LLMConfig
from bot_worker.services import (
    CORE_JOBS,
    AlertDeliveryConfig,
    record_job_run,
    run_pending_investigations,
    run_pipeline,
)


@worker_app.command("start")
def worker_start(only: Annotated[str | None, typer.Option("--only")] = None) -> None:
    """Start the background worker process to run pipeline jobs at configured intervals."""
    jobs = only.split(",") if only else CORE_JOBS
    typer.echo(f"Starting worker loop for jobs: {', '.join(jobs)}")
    typer.echo("Use Ctrl+C to stop")

    async def loop() -> None:
        while True:

            async def action(session):
                settings = _settings()
                result = await run_pipeline(
                    session,
                    freshness_hours=settings.ingestion.rss_freshness_hours,
                    embedding_config=EmbeddingConfig.from_settings(settings),
                    llm_config=LLMConfig.from_settings(settings),
                    investigation_config=InvestigationConfig.from_settings(settings),
                    alert_delivery_config=AlertDeliveryConfig.from_settings(settings),
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

            await _with_session(action)
            await asyncio.sleep(_settings().bot.polling_interval_seconds)

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
