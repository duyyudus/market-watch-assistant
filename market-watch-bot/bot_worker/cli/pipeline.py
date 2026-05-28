from __future__ import annotations

from typing import Annotated

import typer

from bot_worker.cli.apps import pipeline_app
from bot_worker.cli.common import _db_error, _echo_json, _run, _settings, _with_session
from bot_worker.embeddings import EmbeddingConfig
from bot_worker.investigation import InvestigationConfig
from bot_worker.llm import LLMConfig
from bot_worker.services import (
    AlertDeliveryConfig,
    record_job_run,
    run_pipeline,
)


@pipeline_app.command("run")
def pipeline_run(dry_run: Annotated[bool, typer.Option("--dry-run")] = False) -> None:
    """Execute the complete market watch ingestion and analysis pipeline."""
    if dry_run:
        typer.echo(
            "Dry run pipeline: poll -> normalize -> dedupe -> embed -> "
            "cluster -> llm enrich -> market -> score -> alert"
        )
        return

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
        _echo_json(result)

    try:
        _run(_with_session(action))
    except Exception as exc:  # noqa: BLE001
        _db_error(exc)
        raise typer.Exit(1) from exc
@pipeline_app.command("inspect")
def pipeline_inspect(item: Annotated[str, typer.Option("--item")]) -> None:
    """Inspect details of a specific pipeline run or item (MVP placeholder)."""
    typer.echo(f"Pipeline inspection for {item} is available after database ingestion")
@pipeline_app.command("stats")
def pipeline_stats() -> None:
    """Show statistics and retention cutoffs for the pipeline."""
    from bot_worker.cli.health import health_pipeline

    health_pipeline()
