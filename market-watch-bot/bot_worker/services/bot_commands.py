from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot_worker.db.models import BotCommand, EventCluster, NewsSource
from bot_worker.embeddings import EmbeddingConfig
from bot_worker.investigation import InvestigationConfig
from bot_worker.llm import LLMConfig
from bot_worker.scoring import ScoreInput, score_event
from bot_worker.services.alert_delivery import AlertDeliveryConfig, dispatch_pending_alerts
from bot_worker.services.events import recluster_recent_event_clusters
from bot_worker.services.investigation import run_event_investigation
from bot_worker.services.jobs import record_job_run
from bot_worker.services.market import market_move_score_for_cluster
from bot_worker.services.pipeline import run_pipeline
from bot_worker.services.retention import RetentionPolicy, retention_preview, run_retention
from bot_worker.services.sources import fetch_source

ALLOWED_COMMAND_TYPES = {
    "pipeline.run",
    "source.fetch",
    "alert.dispatch",
    "event.rescore",
    "event.mark",
    "event.recluster",
    "investigation.run_event",
    "retention.preview",
    "retention.run",
}

EVENT_STATUSES = {"reported", "confirmed", "official", "stale", "false_signal", "merged"}


def utcnow() -> datetime:
    return datetime.now(UTC)


def since_cutoff(value: str) -> datetime:
    stripped = value.strip().lower()
    now = utcnow()
    if stripped.endswith("d") and stripped[:-1].isdigit():
        return now - timedelta(days=int(stripped[:-1]))
    if stripped.endswith("h") and stripped[:-1].isdigit():
        return now - timedelta(hours=int(stripped[:-1]))
    return datetime.fromisoformat(value).astimezone(UTC)


async def claim_pending_bot_command(session: AsyncSession) -> BotCommand | None:
    result = await session.scalars(
        select(BotCommand)
        .where(BotCommand.status == "pending")
        .order_by(BotCommand.created_at.asc())
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    command = result.first()
    if command is None:
        return None
    command.status = "running"
    command.started_at = utcnow()
    command.error_message = None
    await session.flush()
    return command


async def score_event_cluster(session: AsyncSession, event: EventCluster):
    market_score = await market_move_score_for_cluster(session, event)
    return score_event(
        ScoreInput(
            top_source_score=event.top_source_score,
            source_count=event.source_count,
            watchlist_tier="A" if event.affected_entities else None,
            is_duplicate=False,
            is_stale=event.status == "stale",
            status=event.status,
            market_move_score=market_score,
        )
    )


def apply_event_score(event: EventCluster, breakdown) -> None:
    event.market_impact_score = breakdown.market_move_score
    event.confirmation_score = breakdown.confidence_score
    event.novelty_score = breakdown.novelty_score
    event.urgency_score = breakdown.urgency_score
    event.relevance_score = breakdown.relevance_score
    event.final_score = breakdown.final_score


def complete_bot_command(command: BotCommand, result: dict[str, object]) -> None:
    command.status = "succeeded"
    command.result = result
    command.completed_at = utcnow()


def fail_bot_command(command: BotCommand, exc: Exception) -> None:
    command.status = "failed"
    command.error_message = str(exc)
    command.completed_at = utcnow()


async def execute_bot_command(
    session: AsyncSession,
    command: BotCommand,
    *,
    settings,
) -> dict[str, object]:
    payload = command.payload or {}
    command_type = command.command_type
    if command_type not in ALLOWED_COMMAND_TYPES:
        raise ValueError(f"Unsupported bot command: {command_type}")

    if command_type == "pipeline.run":
        result = await run_pipeline(
            session,
            dry_run=bool(payload.get("dry_run", False)),
            freshness_hours=settings.ingestion.rss_freshness_hours,
            embedding_config=EmbeddingConfig.from_settings(settings),
            llm_config=LLMConfig.from_settings(settings),
            investigation_config=InvestigationConfig.from_settings(settings),
            alert_delivery_config=AlertDeliveryConfig.from_settings(settings),
        )
        await record_job_run(session, "pipeline", result)
        return dict(result)

    if command_type == "source.fetch":
        source_id = str(payload["source_id"])
        source = await session.get(NewsSource, source_id)
        if source is None:
            raise ValueError(f"Source not found: {source_id}")
        return dict(await fetch_source(session, source))

    if command_type == "alert.dispatch":
        channel = str(payload.get("channel", "telegram"))
        result = await dispatch_pending_alerts(
            session,
            AlertDeliveryConfig.from_settings(settings, channel=channel),
            limit=int(payload.get("limit", 20)),
            dry_run=bool(payload.get("dry_run", False)),
        )
        return dict(result)

    if command_type == "event.rescore":
        event_id = str(payload["event_id"])
        event = await session.get(EventCluster, event_id)
        if event is None:
            raise ValueError(f"Event not found: {event_id}")
        breakdown = await score_event_cluster(session, event)
        apply_event_score(event, breakdown)
        return {"event_id": event.id, "final_score": event.final_score}

    if command_type == "event.mark":
        event_id = str(payload["event_id"])
        status = str(payload["status"])
        if status not in EVENT_STATUSES:
            raise ValueError(f"Unsupported event status: {status}")
        event = await session.get(EventCluster, event_id)
        if event is None:
            raise ValueError(f"Event not found: {event_id}")
        event.status = status
        return {"event_id": event.id, "status": event.status}

    if command_type == "event.recluster":
        result = await recluster_recent_event_clusters(
            session,
            since=since_cutoff(str(payload.get("since", "48h"))),
            dry_run=not bool(payload.get("apply", False)),
            limit=int(payload.get("limit", 500)),
        )
        return dict(result)

    if command_type == "investigation.run_event":
        run = await run_event_investigation(
            session,
            event_id=str(payload["event_id"]),
            config=InvestigationConfig.from_settings(settings),
            llm_config=LLMConfig.from_settings(settings),
        )
        return {"investigation_id": run.id, "status": run.status, "result": run.result or {}}

    policy = RetentionPolicy(
        fetch_logs_days=settings.retention.fetch_logs_days,
        raw_news_items_days=settings.retention.raw_news_items_days,
        normalized_news_items_days=settings.retention.normalized_news_items_days,
        event_clusters_days=settings.retention.event_clusters_days,
        alert_decisions_days=settings.retention.alert_decisions_days,
    )
    if command_type == "retention.preview":
        return {"deleted_counts": await retention_preview(session, policy)}
    if command_type == "retention.run":
        return {"deleted_counts": await run_retention(session, policy)}

    raise ValueError(f"Unsupported bot command: {command_type}")


async def process_one_bot_command(session: AsyncSession, *, settings) -> BotCommand | None:
    command = await claim_pending_bot_command(session)
    if command is None:
        return None
    try:
        result = await execute_bot_command(session, command, settings=settings)
    except Exception as exc:  # noqa: BLE001 - command result must capture operational failures
        fail_bot_command(command, exc)
    else:
        complete_bot_command(command, result)
    return command


async def process_pending_bot_commands(
    session: AsyncSession,
    *,
    settings,
    limit: int = 25,
) -> list[BotCommand]:
    processed: list[BotCommand] = []
    for _ in range(limit):
        command = await process_one_bot_command(session, settings=settings)
        if command is None:
            break
        processed.append(command)
    return processed
