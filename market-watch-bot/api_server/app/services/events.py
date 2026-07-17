from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timedelta

from sqlalchemy import and_, func, not_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import ColumnElement

from api_server.app.schemas import AlertRead, EventDetailRead, EventRead
from api_server.app.services.query import apply_pagination, count_for
from common.config import Settings
from common.db.models import (
    AgentInvestigation,
    BotCommand,
    DigestRecord,
    EventCluster,
    EventClusterItem,
    EventScoreHistory,
    JobRun,
    LLMAnalysisRun,
    MarketMove,
    NormalizedNewsItem,
    utcnow,
)
from common.db.models import (
    AlertDecisionRecord as AlertDecision,
)
from common.llm import LLMConfig, llm_provider, normalize_text, prompt_hash

RELATED_NEWS_SUMMARY_PROMPT_VERSION = "event-related-news-summary-v2"
NO_FULL_TEXT_MESSAGE = (
    "At least one related news item needs full article text before a summary can be generated."
)


def _segment_filter(segment: str) -> ColumnElement[bool] | None:
    """Translate a dashboard market segment into a JSONB membership predicate.

    Crypto, Vietnam, and US are positive matches on the canonical region/asset-class
    vocabulary, which are mutually exclusive; ``global`` is everything that is none of
    those (i.e. non-US international/macro), so a quiet segment can still surface its
    own clusters instead of being crowded out of a recency window shared across all
    segments.
    """
    crypto = or_(
        EventCluster.asset_classes.contains(["crypto"]),
        EventCluster.regions.contains(["crypto"]),
    )
    vietnam = or_(
        EventCluster.regions.contains(["vietnam"]),
        EventCluster.regions.contains(["vn"]),
        EventCluster.asset_classes.contains(["vietnam_equity"]),
    )
    us = or_(
        EventCluster.regions.contains(["us"]),
        EventCluster.regions.contains(["usa"]),
    )
    if segment == "crypto":
        return crypto
    if segment == "vietnam":
        return vietnam
    if segment == "us":
        return us
    if segment == "global":
        return and_(not_(crypto), not_(vietnam), not_(us))
    return None


async def list_events(
    session: AsyncSession,
    *,
    limit: int,
    offset: int,
    max_items: int | None,
    min_score: int | None,
    status_filter: str | None,
    q: str | None,
    segment: str | None = None,
) -> tuple[list[dict[str, object]], int]:
    report_ranges = _report_range_subquery()
    report_end_at = report_ranges.c.report_end_at
    stmt = (
        select(
            EventCluster,
            report_ranges.c.report_start_at,
            report_end_at,
        )
        .outerjoin(report_ranges, report_ranges.c.event_cluster_id == EventCluster.id)
        .order_by(
            report_end_at.is_(None),
            report_end_at.desc(),
            EventCluster.last_updated_at.desc(),
            EventCluster.created_at.desc(),
        )
    )
    if status_filter:
        stmt = stmt.where(EventCluster.status == status_filter)
    if min_score is not None:
        stmt = stmt.where(EventCluster.final_score >= min_score)
    if q:
        stmt = stmt.where(EventCluster.canonical_headline.ilike(f"%{q}%"))
    if segment:
        segment_predicate = _segment_filter(segment)
        if segment_predicate is not None:
            stmt = stmt.where(segment_predicate)
    matching_total = await count_for(session, stmt)
    total = min(matching_total, max_items) if max_items is not None else matching_total
    if offset >= total:
        rows = []
    else:
        effective_limit = min(limit, total - offset)
        page_stmt = apply_pagination(stmt, limit=effective_limit, offset=offset)
        rows = list((await session.execute(page_stmt)).all())
    return (
        [
            event_read_payload(
                event,
                report_start_at=report_start_at,
                report_end_at=report_end_at,
            )
            for event, report_start_at, report_end_at in rows
        ],
        total,
    )


def _effective_report_time_expr() -> ColumnElement[datetime]:
    return func.coalesce(
        NormalizedNewsItem.published_at,
        NormalizedNewsItem.fetched_at,
        NormalizedNewsItem.created_at,
    )


def report_range_subquery():
    effective_report_time = _effective_report_time_expr()
    return (
        select(
            EventClusterItem.event_cluster_id.label("event_cluster_id"),
            func.min(effective_report_time).label("report_start_at"),
            func.max(effective_report_time).label("report_end_at"),
        )
        .join(NormalizedNewsItem, NormalizedNewsItem.id == EventClusterItem.news_item_id)
        .group_by(EventClusterItem.event_cluster_id)
        .subquery()
    )


def _report_range_subquery():
    return report_range_subquery()


async def report_ranges_by_event_id(
    session: AsyncSession,
    event_ids: list[str],
) -> dict[str, tuple[datetime | None, datetime | None]]:
    if not event_ids:
        return {}
    report_ranges = _report_range_subquery()
    rows = (
        await session.execute(
            select(
                report_ranges.c.event_cluster_id,
                report_ranges.c.report_start_at,
                report_ranges.c.report_end_at,
            ).where(report_ranges.c.event_cluster_id.in_(event_ids))
        )
    ).all()
    return {
        event_id: (report_start_at, report_end_at)
        for event_id, report_start_at, report_end_at in rows
    }


def event_read_payload(
    event: EventCluster,
    *,
    report_start_at: datetime | None,
    report_end_at: datetime | None,
) -> dict[str, object]:
    payload = EventRead.model_validate(event).model_dump()
    payload["report_start_at"] = report_start_at
    payload["report_end_at"] = report_end_at
    return payload


def event_summary_payload(
    event: EventCluster,
    report_range: tuple[datetime | None, datetime | None] | None,
) -> dict[str, object]:
    report_start_at, report_end_at = report_range or (None, None)
    return {
        "id": event.id,
        "headline": event.canonical_headline,
        "final_score": event.final_score,
        "status": event.status,
        "report_start_at": report_start_at,
        "report_end_at": report_end_at,
    }


async def get_event_detail(session: AsyncSession, event: EventCluster) -> dict[str, object]:
    report_range = (await report_ranges_by_event_id(session, [event.id])).get(event.id)
    report_start_at, report_end_at = report_range or (None, None)
    latest_alert = await session.scalar(
        select(AlertDecision)
        .where(AlertDecision.event_cluster_id == event.id)
        .order_by(AlertDecision.created_at.desc())
        .limit(1)
    )
    latest_investigation = await session.scalar(
        select(AgentInvestigation)
        .where(AgentInvestigation.target_type == "event_cluster")
        .where(AgentInvestigation.target_id == event.id)
        .order_by(AgentInvestigation.created_at.desc())
        .limit(1)
    )
    score_history = await list_event_score_history(session, event_id=event.id, limit=20)
    timeline_rows = (
        await session.execute(
            select(EventClusterItem, NormalizedNewsItem)
            .join(NormalizedNewsItem, NormalizedNewsItem.id == EventClusterItem.news_item_id)
            .where(EventClusterItem.event_cluster_id == event.id)
            .order_by(EventClusterItem.added_at.asc(), NormalizedNewsItem.fetched_at.asc())
        )
    ).all()
    llm_runs = list(
        (
            await session.scalars(
                select(LLMAnalysisRun)
                .where(LLMAnalysisRun.target_type == "event_cluster")
                .where(LLMAnalysisRun.target_id == event.id)
                .order_by(LLMAnalysisRun.created_at.desc())
                .limit(10)
            )
        ).all()
    )
    market_moves: list[MarketMove] = []
    if event.affected_tickers:
        start_at = (event.first_seen_at or event.created_at) - timedelta(hours=24)
        end_at = (event.last_updated_at or event.updated_at) + timedelta(hours=24)
        ranked_market_moves = (
            select(
                MarketMove.id.label("id"),
                func.row_number()
                .over(
                    partition_by=(
                        MarketMove.asset_symbol,
                        MarketMove.window,
                        MarketMove.exchange,
                    ),
                    order_by=(
                        MarketMove.timestamp.desc(),
                        MarketMove.created_at.desc(),
                        MarketMove.id.desc(),
                    ),
                )
                .label("snapshot_rank"),
            )
            .where(MarketMove.asset_symbol.in_(event.affected_tickers))
            .where(MarketMove.timestamp >= start_at)
            .where(MarketMove.timestamp <= end_at)
            .subquery()
        )
        market_moves = list(
            (
                await session.scalars(
                    select(MarketMove)
                    .join(ranked_market_moves, MarketMove.id == ranked_market_moves.c.id)
                    .where(ranked_market_moves.c.snapshot_rank == 1)
                    .order_by(MarketMove.timestamp.desc())
                    .limit(20)
                )
            ).all()
        )
    payload = {
        **event_read_payload(
            event,
            report_start_at=report_start_at,
            report_end_at=report_end_at,
        ),
        "latest_alert": (
            AlertRead(
                **latest_alert.__dict__,
                event=event_summary_payload(event, report_range),
            ).model_dump()
            if latest_alert
            else None
        ),
        "latest_investigation": (
            {
                "id": latest_investigation.id,
                "status": latest_investigation.status,
                "trigger_reason": latest_investigation.trigger_reason,
                "result": latest_investigation.result,
                "error_message": latest_investigation.error_message,
                "created_at": latest_investigation.created_at,
            }
            if latest_investigation
            else None
        ),
        "score_history": [
            {
                "id": row.id,
                "final_score": row.final_score,
                "score_breakdown": row.score_breakdown,
                "created_at": row.created_at,
            }
            for row in score_history
        ],
        "timeline": [
            {
                "news_item_id": item.news_item_id,
                "title": news.title,
                "source_name": news.source_name,
                "source_score": news.source_score,
                "url": news.url,
                "published_at": news.published_at,
                "fetched_at": news.fetched_at,
                "added_at": item.added_at,
                "relation_type": item.relation_type,
                "similarity_score": item.similarity_score,
                "decision_metadata": item.decision_metadata,
            }
            for item, news in timeline_rows
        ],
        "llm_runs": [
            {
                "id": run.id,
                "provider": run.provider,
                "model": run.model,
                "prompt_version": run.prompt_version,
                "result": run.result,
                "status": run.status,
                "error_message": run.error_message,
                "usage": run.usage,
                "created_at": run.created_at,
                "updated_at": run.updated_at,
            }
            for run in llm_runs
        ],
        "market_moves": [
            {
                "id": move.id,
                "asset_symbol": move.asset_symbol,
                "asset_class": move.asset_class,
                "exchange": move.exchange,
                "timestamp": move.timestamp,
                "window": move.window,
                "price_change_pct": move.price_change_pct,
                "volume_change_pct": move.volume_change_pct,
                "value_traded_change_pct": move.value_traded_change_pct,
                "z_score": move.z_score,
            }
            for move in market_moves
        ],
    }
    return EventDetailRead.model_validate(payload).model_dump()


async def summarize_related_news(
    session: AsyncSession,
    event: EventCluster,
    *,
    settings: Settings,
) -> dict[str, object]:
    rows = (
        await session.execute(
            select(EventClusterItem, NormalizedNewsItem)
            .join(NormalizedNewsItem, NormalizedNewsItem.id == EventClusterItem.news_item_id)
            .where(EventClusterItem.event_cluster_id == event.id)
            .order_by(EventClusterItem.added_at.asc(), NormalizedNewsItem.fetched_at.asc())
        )
    ).all()
    news_items = [news for _item, news in rows]
    full_text_items = [news for news in news_items if _usable_article_text(news)]
    if not full_text_items:
        return {
            "status": "no_full_text",
            "event_id": event.id,
            "message": NO_FULL_TEXT_MESSAGE,
            "language": None,
            "summary": None,
            "why_it_matters": None,
            "digest_bullets": [],
            "caveats": [],
            "news_item_count": len(news_items),
            "full_text_item_count": 0,
            "run_id": None,
            "usage": None,
        }

    config = LLMConfig.from_settings(settings)
    if not config.enabled:
        config = replace(config, enabled=True)
    if not config.api_key:
        raise ValueError(f"{config.api_key_env} is required for related news summaries")

    input_snapshot = _related_news_summary_snapshot(event, rows)
    prompt = _build_related_news_summary_prompt(event, input_snapshot)
    run = await _prepare_related_news_summary_run(
        session,
        event_id=event.id,
        config=config,
        prompt=prompt,
        input_snapshot=input_snapshot,
    )
    await session.flush()

    try:
        result, usage = await llm_provider(config).summarize_related_news(prompt)
    except Exception as exc:
        run.status = "failed"
        run.error_message = str(exc)
        run.updated_at = utcnow()
        await session.flush()
        raise

    result_payload = result.model_dump()
    run.status = "succeeded"
    run.result = result_payload
    run.usage = usage
    run.error_message = None
    run.updated_at = utcnow()
    await session.flush()
    return {
        "status": "generated",
        "event_id": event.id,
        "message": None,
        "language": result.language,
        "summary": result.summary,
        "why_it_matters": result.why_it_matters,
        "digest_bullets": result.digest_bullets,
        "caveats": result.caveats,
        "news_item_count": len(news_items),
        "full_text_item_count": len(full_text_items),
        "run_id": run.id,
        "usage": usage,
    }


def _usable_article_text(news: NormalizedNewsItem) -> bool:
    return bool((news.raw_content or "").strip())


def _related_news_summary_snapshot(
    event: EventCluster,
    rows: list[tuple[EventClusterItem, NormalizedNewsItem]],
) -> dict[str, object]:
    return {
        "event": {
            "id": event.id,
            "headline": event.canonical_headline,
            "summary": event.summary,
            "status": event.status,
            "regions": event.regions,
            "asset_classes": event.asset_classes,
            "affected_entities": event.affected_entities,
            "affected_tickers": event.affected_tickers,
            "source_count": event.source_count,
            "final_score": event.final_score,
        },
        "news_items": [
            {
                "id": news.id,
                "title": news.title,
                "snippet": news.snippet,
                "source_name": news.source_name,
                "source_score": news.source_score,
                "language": news.language,
                "url": news.url,
                "published_at": _isoformat(news.published_at),
                "fetched_at": _isoformat(news.fetched_at),
                "relation_type": item.relation_type,
                "similarity_score": item.similarity_score,
                "full_text_available": bool((news.raw_content or "").strip()),
                "article_text": normalize_text(news.raw_content or "")
                if _usable_article_text(news)
                else None,
            }
            for item, news in rows
        ],
    }


def _isoformat(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _build_related_news_summary_prompt(
    event: EventCluster,
    input_snapshot: dict[str, object],
) -> str:
    return "\n".join(
        [
            "Summarize all related news for this selected market event.",
            "Return only JSON matching the requested schema.",
            "Cover every important point that contributes to the event. Distinguish facts "
            "supported by full article text from partial title/snippet-only context.",
            "Detect the predominant language by counting only articles with full text. "
            "Use the language of the highest-scored full-text source to break a count tie; "
            "if still tied, use the first article in the supplied order. Detect from article "
            "content and treat stored language metadata only as a hint.",
            "Write summary, digest_bullets, why_it_matters, and caveats entirely in the "
            "selected language. Return that language as a lowercase BCP 47-style code.",
            "Keep the summary concise but complete enough for an alert detail popover.",
            "",
            f"Event cluster id: {event.id}",
            f"Headline: {normalize_text(event.canonical_headline)}",
            f"Existing summary: {normalize_text(event.summary or '')}",
            f"Status: {event.status}",
            f"Regions: {', '.join(event.regions or [])}",
            f"Asset classes: {', '.join(event.asset_classes or [])}",
            f"Affected entities: {', '.join(event.affected_entities or [])}",
            f"Affected tickers: {', '.join(event.affected_tickers or [])}",
            f"Final score: {event.final_score}",
            "",
            "Related news snapshot:",
            json.dumps(input_snapshot["news_items"], default=str, ensure_ascii=False),
        ]
    )


async def _prepare_related_news_summary_run(
    session: AsyncSession,
    *,
    event_id: str,
    config: LLMConfig,
    prompt: str,
    input_snapshot: dict[str, object],
) -> LLMAnalysisRun:
    existing_run = await session.scalar(
        select(LLMAnalysisRun).where(
            LLMAnalysisRun.target_type == "event_cluster_news_summary",
            LLMAnalysisRun.target_id == event_id,
            LLMAnalysisRun.provider == config.provider,
            LLMAnalysisRun.model == config.model,
            LLMAnalysisRun.prompt_version == RELATED_NEWS_SUMMARY_PROMPT_VERSION,
        )
    )
    if existing_run is None:
        run = LLMAnalysisRun(
            target_type="event_cluster_news_summary",
            target_id=event_id,
            provider=config.provider,
            model=config.model,
            prompt_version=RELATED_NEWS_SUMMARY_PROMPT_VERSION,
            prompt_hash=prompt_hash(prompt),
            input_snapshot=input_snapshot,
            status="running",
        )
        session.add(run)
        return run
    existing_run.prompt_hash = prompt_hash(prompt)
    existing_run.input_snapshot = input_snapshot
    existing_run.result = None
    existing_run.status = "running"
    existing_run.error_message = None
    existing_run.usage = None
    existing_run.updated_at = utcnow()
    return existing_run


async def get_latest_digest(session: AsyncSession) -> DigestRecord | None:
    stmt = select(DigestRecord).order_by(DigestRecord.created_at.desc()).limit(1)
    return (await session.scalars(stmt)).first()


async def list_digest_preview(session: AsyncSession, *, limit: int) -> list[EventCluster]:
    stmt = (
        select(EventCluster)
        .where(EventCluster.final_score >= 30)
        .where(EventCluster.status.notin_(["stale", "false_signal", "merged"]))
        .order_by(EventCluster.final_score.desc(), EventCluster.last_updated_at.desc())
        .limit(limit)
    )
    return list((await session.scalars(stmt)).all())


async def list_event_score_history(
    session: AsyncSession,
    *,
    event_id: str,
    limit: int | None = None,
) -> list[EventScoreHistory]:
    stmt = (
        select(EventScoreHistory)
        .where(EventScoreHistory.event_cluster_id == event_id)
        .order_by(EventScoreHistory.created_at.desc())
    )
    if limit is not None:
        stmt = stmt.limit(limit)
    return list((await session.scalars(stmt)).all())


async def list_stream_events(
    session: AsyncSession,
    *,
    replay: bool,
    limit: int,
) -> list[dict[str, object]]:
    if not replay:
        return []
    events: list[dict[str, object]] = [{"event": "heartbeat", "data": {"status": "ok"}}]
    alerts = list(
        (
            await session.scalars(
                select(AlertDecision).order_by(AlertDecision.created_at.desc()).limit(limit)
            )
        ).all()
    )
    jobs = list(
        (
            await session.scalars(
                select(JobRun).order_by(JobRun.started_at.desc()).limit(limit)
            )
        ).all()
    )
    commands = list(
        (
            await session.scalars(
                select(BotCommand).order_by(BotCommand.created_at.desc()).limit(limit)
            )
        ).all()
    )
    events.extend(
        {
            "event": "alert.created",
            "data": {
                "id": alert.id,
                "event_cluster_id": alert.event_cluster_id,
                "decision": alert.decision,
                "created_at": alert.created_at,
            },
        }
        for alert in alerts
    )
    events.extend(
        {
            "event": "pipeline.completed",
            "data": {
                "id": job.id,
                "job_name": job.job_name,
                "status": job.status,
                "completed_at": job.completed_at,
            },
        }
        for job in jobs
        if job.job_name == "pipeline" and job.completed_at is not None
    )
    events.extend(
        {
            "event": "command.updated",
            "data": {
                "id": command.id,
                "command_type": command.command_type,
                "status": command.status,
                "completed_at": command.completed_at,
            },
        }
        for command in commands
    )
    return events[:limit]


async def list_stream_events_since(
    session: AsyncSession,
    *,
    since: datetime,
    limit: int,
) -> tuple[list[dict[str, object]], datetime]:
    alerts = list(
        (
            await session.scalars(
                select(AlertDecision)
                .where(AlertDecision.created_at > since)
                .order_by(AlertDecision.created_at.asc(), AlertDecision.id.asc())
                .limit(limit)
            )
        ).all()
    )
    jobs = list(
        (
            await session.scalars(
                select(JobRun)
                .where(JobRun.job_name == "pipeline")
                .where(JobRun.completed_at.is_not(None))
                .where(JobRun.completed_at > since)
                .order_by(JobRun.completed_at.asc(), JobRun.id.asc())
                .limit(limit)
            )
        ).all()
    )
    commands = list(
        (
            await session.scalars(
                select(BotCommand)
                .where(
                    or_(
                        BotCommand.created_at > since,
                        BotCommand.started_at > since,
                        BotCommand.completed_at > since,
                    )
                )
                .order_by(BotCommand.created_at.asc(), BotCommand.id.asc())
                .limit(limit)
            )
        ).all()
    )

    cursor = since
    events: list[tuple[datetime, dict[str, object]]] = []
    for alert in alerts:
        cursor = max(cursor, alert.created_at)
        events.append(
            (
                alert.created_at,
                {
                    "event": "alert.created",
                    "data": {
                        "id": alert.id,
                        "event_cluster_id": alert.event_cluster_id,
                        "decision": alert.decision,
                        "created_at": alert.created_at,
                    },
                },
            )
        )
    for job in jobs:
        if job.completed_at is None:
            continue
        cursor = max(cursor, job.completed_at)
        events.append(
            (
                job.completed_at,
                {
                    "event": "pipeline.completed",
                    "data": {
                        "id": job.id,
                        "job_name": job.job_name,
                        "status": job.status,
                        "completed_at": job.completed_at,
                    },
                },
            )
        )
    for command in commands:
        timestamp = command.completed_at or command.started_at or command.created_at
        cursor = max(cursor, timestamp)
        events.append(
            (
                timestamp,
                {
                    "event": "command.updated",
                    "data": {
                        "id": command.id,
                        "command_type": command.command_type,
                        "status": command.status,
                        "completed_at": command.completed_at,
                    },
                },
            )
        )
    return [event for _, event in sorted(events, key=lambda item: item[0])[:limit]], cursor


def stream_cursor_now() -> datetime:
    return utcnow()
