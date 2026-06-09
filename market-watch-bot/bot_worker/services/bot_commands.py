from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot_worker.db.models import AlertChannel, BotCommand, EventCluster, NewsSource
from bot_worker.embeddings import EmbeddingConfig
from bot_worker.investigation import InvestigationConfig
from bot_worker.scoring import ScoreInput, score_event
from bot_worker.services.alert_delivery import (
    AlertDeliveryConfig,
    dispatch_pending_alerts,
    send_test_alert_to_channel,
)
from bot_worker.services.digests import build_digest_record, send_digest_record
from bot_worker.services.events import (
    compact_archived_events,
    merge_event_clusters,
    recluster_recent_event_clusters,
    split_event_cluster,
)
from bot_worker.services.investigation import run_event_investigation
from bot_worker.services.jobs import record_job_run
from bot_worker.services.market import (
    fetch_market_moves,
    market_move_score_for_cluster,
    run_missed_catalyst_review,
    store_market_moves,
)
from bot_worker.services.pipeline import run_pipeline
from bot_worker.services.retention import RetentionPolicy, retention_preview, run_retention
from bot_worker.services.sources import fetch_source, refresh_source_quality_scores
from bot_worker.services.watchlists import tier_for_entities, watchlist_entries
from common.bot_commands import ALLOWED_COMMAND_TYPES, EVENT_STATUSES
from common.llm import LLMConfig


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


async def reap_stale_running_bot_commands(
    session: AsyncSession,
    *,
    timeout_seconds: int,
    now: datetime | None = None,
) -> int:
    current = now or utcnow()
    cutoff = current - timedelta(seconds=timeout_seconds)
    if hasattr(session, "commands"):
        candidates = [
            command
            for command in session.commands
            if command.status == "running" and command.started_at and command.started_at < cutoff
        ]
        for command in candidates:
            command.status = "failed"
            command.error_message = "timed out (worker restart?)"
            command.completed_at = current
        if candidates:
            await session.flush()
        return len(candidates)
    result = await session.scalars(
        select(BotCommand)
        .where(BotCommand.status == "running", BotCommand.started_at < cutoff)
        .order_by(BotCommand.started_at.asc())
    )
    reaped = 0
    for command in result.all():
        command.status = "failed"
        command.error_message = "timed out (worker restart?)"
        command.completed_at = current
        reaped += 1
    if reaped:
        await session.flush()
    return reaped


async def score_event_cluster(session: AsyncSession, event: EventCluster):
    market_score = await market_move_score_for_cluster(session, event)
    watch_entries = await watchlist_entries(session)
    return score_event(
        ScoreInput(
            top_source_score=event.top_source_score,
            source_count=event.source_count,
            watchlist_tier=tier_for_entities(
                entities=event.affected_entities or [],
                tickers=event.affected_tickers or [],
                entries=watch_entries,
            ),
            is_duplicate=False,
            is_stale=event.status == "stale",
            unique_high_quality_source_count=int(event.high_quality_source_count or 0),
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
            tracking_params=getattr(settings.ingestion, "tracking_params", None),
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

    if command_type == "alert.test_channel":
        channel_id = str(payload["channel_id"])
        channel = await session.get(AlertChannel, channel_id)
        if channel is None:
            raise ValueError(f"Alert channel not found: {channel_id}")
        return dict(
            await send_test_alert_to_channel(
                session,
                channel,
                AlertDeliveryConfig.from_settings(settings, channel=channel.channel_type),
                str(payload.get("message", "Market watch alert delivery test.")),
            )
        )

    if command_type == "digest.send":
        until = utcnow()
        since = until - timedelta(hours=int(payload.get("hours", 24)))
        digest = await build_digest_record(
            session,
            since=since,
            until=until,
            threshold=settings.alerts.digest_threshold,
            limit=int(payload.get("limit", 50)),
        )
        if bool(payload.get("dry_run", False)):
            return {
                "digest_id": digest.id,
                "status": digest.status,
                "event_count": digest.event_count,
                "content": digest.content,
            }
        digest = await send_digest_record(
            session,
            digest,
            AlertDeliveryConfig.from_settings(settings, channel="telegram"),
        )
        return {"digest_id": digest.id, "status": digest.status, "event_count": digest.event_count}

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

    if command_type == "event.merge":
        return dict(
            await merge_event_clusters(
                session,
                source_id=str(payload["source_event_id"]),
                target_id=str(payload["target_event_id"]),
            )
        )

    if command_type == "event.split":
        news_item_ids = payload["news_item_ids"]
        if isinstance(news_item_ids, str):
            parsed_news_item_ids = [
                item.strip() for item in news_item_ids.split(",") if item.strip()
            ]
        else:
            parsed_news_item_ids = [str(item) for item in news_item_ids]
        return dict(
            await split_event_cluster(
                session,
                source_id=str(payload["event_id"]),
                news_item_ids=parsed_news_item_ids,
            )
        )

    if command_type == "event.compact_archived":
        older_than = since_cutoff(str(payload.get("older_than", "30d")))
        return dict(
            await compact_archived_events(
                session,
                older_than=older_than,
                dry_run=not bool(payload.get("apply", False)),
                limit=int(payload.get("limit", 500)),
            )
        )

    if command_type == "source.quality.refresh":
        return dict(await refresh_source_quality_scores(session))

    if command_type == "investigation.run_event":
        run = await run_event_investigation(
            session,
            event_id=str(payload["event_id"]),
            config=InvestigationConfig.from_settings(settings),
            llm_config=LLMConfig.from_settings(settings),
        )
        return {"investigation_id": run.id, "status": run.status, "result": run.result or {}}

    if command_type == "market.fetch":
        custom_symbols = payload.get("symbols")
        window = str(payload.get("window", "1d"))
        if custom_symbols:
            if isinstance(custom_symbols, str):
                symbols = [s.strip() for s in custom_symbols.split(",") if s.strip()]
            else:
                symbols = list(custom_symbols)
        else:
            from bot_worker.services.watchlists import watchlist_entries
            watchlist = await watchlist_entries(session)
            symbols = list({entry.symbol for entry in watchlist if entry.symbol})
        
        if symbols:
            moves = await fetch_market_moves(
                symbols=symbols,
                window=window,
                vn_base_url=settings.market_data.vn_base_url,
                symbol_map=settings.market_data.symbol_map,
                crypto_provider=settings.market_data.crypto_provider,
                crypto_fallback_provider=settings.market_data.crypto_fallback_provider,
            )
            inserted = await store_market_moves(session, moves)
            return {"inserted": inserted, "symbols": symbols, "window": window}
        return {"inserted": 0, "symbols": [], "window": window}

    if command_type == "catalyst.review":
        window = str(payload.get("window", "1d"))
        count = await run_missed_catalyst_review(session, window=window)
        return {"created": count, "window": window}

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
    bot_settings = getattr(settings, "bot", settings)
    await reap_stale_running_bot_commands(
        session,
        timeout_seconds=getattr(bot_settings, "stale_command_timeout_seconds", 600),
    )
    processed: list[BotCommand] = []
    for _ in range(limit):
        command = await process_one_bot_command(session, settings=settings)
        if command is None:
            break
        processed.append(command)
    return processed
