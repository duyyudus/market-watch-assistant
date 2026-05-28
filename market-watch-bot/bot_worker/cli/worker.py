from __future__ import annotations

import asyncio
from typing import Annotated

import typer

from bot_worker.cli.apps import worker_app
from bot_worker.cli.common import _run, _settings, _with_session
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
    """Show worker running status (MVP placeholder)."""
    typer.echo("worker status: command-driven MVP; no supervisor state recorded")
@worker_app.command("logs")
def worker_logs(tail: Annotated[int, typer.Option("--tail")] = 200) -> None:
    """Retrieve logs from the worker process (MVP placeholder)."""
    typer.echo(f"worker logs are stdout/stderr in MVP (tail requested: {tail})")
@worker_app.command("health")
def worker_health() -> None:
    """Check health status of the worker and active database session."""
    from bot_worker.cli.health import health_pipeline

    health_pipeline()
