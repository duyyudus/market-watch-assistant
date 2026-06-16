from __future__ import annotations

from typing import Annotated

import typer
from sqlalchemy import select

from bot_worker.cli.apps import pipeline_app
from bot_worker.cli.common import (
    _db_error,
    _echo_json,
    _record_failed_job,
    _run,
    _settings,
    _with_session,
)
from bot_worker.db.models import (
    AgentInvestigation,
    AlertDecisionRecord,
    EventCluster,
    EventClusterItem,
    LLMAnalysisRun,
    NewsEntity,
    NewsItemEmbedding,
    NormalizedNewsItem,
    RawNewsItem,
)
from bot_worker.db.session import make_session_factory
from bot_worker.embeddings import EmbeddingConfig
from bot_worker.investigation import InvestigationConfig
from bot_worker.services import (
    AlertDeliveryConfig,
    deliver_pending_alerts,
    record_job_run,
    run_pipeline,
)
from common.llm import LLMConfig


@pipeline_app.command("run")
def pipeline_run(dry_run: Annotated[bool, typer.Option("--dry-run")] = False) -> None:
    """Execute the complete market watch ingestion and analysis pipeline."""
    if dry_run:
        typer.echo(
            "Dry run pipeline: poll -> normalize -> dedupe -> embed -> "
            "cluster -> llm enrich -> market -> score -> alert"
        )
        return

    async def action():
        settings = _settings()
        factory = make_session_factory(settings)

        async def pipeline_txn(session):
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
            return result

        try:
            result = await _with_session(
                pipeline_txn, settings=settings, session_factory=factory
            )
        except Exception as exc:
            await _record_failed_job(factory, "pipeline", exc)
            raise

        # Deliver alerts after the pipeline transaction has committed, so a failed
        # delivery can be retried without re-running the whole pipeline.
        delivery_config = AlertDeliveryConfig.from_settings(settings)
        if delivery_config.channel == "telegram":
            counts = await deliver_pending_alerts(factory, delivery_config)
            result["delivered_alerts"] = counts["sent"]
            result["failed_alert_deliveries"] = counts["failed"]
        _echo_json(result)

    try:
        _run(action())
    except Exception as exc:  # noqa: BLE001
        _db_error(exc)
        raise typer.Exit(1) from exc
@pipeline_app.command("inspect")
def pipeline_inspect(item: Annotated[str, typer.Option("--item")]) -> None:
    """Inspect how an item moved through the pipeline."""
    async def action(session):
        if item.startswith("raw_"):
            raw = await session.get(RawNewsItem, item)
            if raw is None:
                typer.echo("Raw news item not found")
                raise typer.Exit(1)
            normalized = (
                await session.scalars(
                    select(NormalizedNewsItem).where(NormalizedNewsItem.raw_item_id == raw.id)
                )
            ).first()
            _echo_json(
                {
                    "target_type": "raw_news_item",
                    "raw_item_id": raw.id,
                    "source_id": raw.source_id,
                    "title": raw.raw_title,
                    "url": raw.raw_url,
                    "fetched_at": raw.fetched_at,
                    "content_hash": raw.content_hash,
                    "normalized_item_id": normalized.id if normalized is not None else None,
                    "processing_status": (
                        normalized.processing_status if normalized is not None else None
                    ),
                }
            )
            return
        if item.startswith("news_"):
            news_item = await session.get(NormalizedNewsItem, item)
            if news_item is None:
                typer.echo("News item not found")
                raise typer.Exit(1)
            entities = list(
                (
                    await session.scalars(
                        select(NewsEntity).where(NewsEntity.news_item_id == news_item.id)
                    )
                ).all()
            )
            cluster_items = list(
                (
                    await session.scalars(
                        select(EventClusterItem).where(
                            EventClusterItem.news_item_id == news_item.id
                        )
                    )
                ).all()
            )
            embedding = await session.scalar(
                select(NewsItemEmbedding).where(NewsItemEmbedding.news_item_id == news_item.id)
            )
            llm_runs = list(
                (
                    await session.scalars(
                        select(LLMAnalysisRun)
                        .where(LLMAnalysisRun.target_type == "news_item")
                        .where(LLMAnalysisRun.target_id == news_item.id)
                    )
                ).all()
            )
            _echo_json(
                {
                    "target_type": "normalized_news_item",
                    "news_item_id": news_item.id,
                    "raw_item_id": news_item.raw_item_id,
                    "processing_status": news_item.processing_status,
                    "title": news_item.title,
                    "source_name": news_item.source_name,
                    "entities": [
                        {
                            "normalized_name": entity.normalized_name,
                            "ticker": entity.ticker,
                            "confidence": entity.confidence,
                        }
                        for entity in entities
                    ],
                    "embedding_present": embedding is not None,
                    "clusters": [
                        {
                            "event_cluster_id": cluster.event_cluster_id,
                            "relation_type": cluster.relation_type,
                            "similarity_score": cluster.similarity_score,
                        }
                        for cluster in cluster_items
                    ],
                    "llm_runs": [
                        {"id": run.id, "status": run.status, "prompt_version": run.prompt_version}
                        for run in llm_runs
                    ],
                }
            )
            return
        if item.startswith("evt_"):
            event = await session.get(EventCluster, item)
            if event is None:
                typer.echo("Event cluster not found")
                raise typer.Exit(1)
            alert = await session.scalar(
                select(AlertDecisionRecord)
                .where(AlertDecisionRecord.event_cluster_id == event.id)
                .order_by(AlertDecisionRecord.created_at.desc())
                .limit(1)
            )
            investigation = await session.scalar(
                select(AgentInvestigation)
                .where(AgentInvestigation.target_type == "event_cluster")
                .where(AgentInvestigation.target_id == event.id)
                .order_by(AgentInvestigation.created_at.desc())
                .limit(1)
            )
            _echo_json(
                {
                    "target_type": "event_cluster",
                    "event_cluster_id": event.id,
                    "headline": event.canonical_headline,
                    "status": event.status,
                    "final_score": event.final_score,
                    "alert_decision_id": alert.id if alert is not None else None,
                    "investigation_id": investigation.id if investigation is not None else None,
                }
            )
            return
        if item.startswith("alert_"):
            alert = await session.get(AlertDecisionRecord, item)
            if alert is None:
                typer.echo("Alert decision not found")
                raise typer.Exit(1)
            _echo_json(
                {
                    "target_type": "alert_decision",
                    "alert_decision_id": alert.id,
                    "event_cluster_id": alert.event_cluster_id,
                    "decision": alert.decision,
                    "reason": alert.reason,
                    "channel": alert.channel,
                    "sent_at": alert.sent_at,
                }
            )
            return
        if item.startswith("inv_"):
            investigation = await session.get(AgentInvestigation, item)
            if investigation is None:
                typer.echo("Investigation not found")
                raise typer.Exit(1)
            _echo_json(
                {
                    "target_type": "agent_investigation",
                    "investigation_id": investigation.id,
                    "target": {
                        "type": investigation.target_type,
                        "id": investigation.target_id,
                    },
                    "status": investigation.status,
                    "result": investigation.result,
                    "error": investigation.error_message,
                }
            )
            return
        typer.echo("Unsupported item id prefix")
        raise typer.Exit(1)

    _run(_with_session(action))
@pipeline_app.command("stats")
def pipeline_stats() -> None:
    """Show statistics and retention cutoffs for the pipeline."""
    from bot_worker.cli.health import health_pipeline

    health_pipeline()
