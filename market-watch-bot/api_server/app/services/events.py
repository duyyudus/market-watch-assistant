from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import ColumnElement

from api_server.app.schemas import AlertRead, EventDetailRead, EventRead
from api_server.app.services.query import apply_pagination, count_for
from common.db.models import (
    AgentInvestigation,
    BotCommand,
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


async def list_events(
    session: AsyncSession,
    *,
    limit: int,
    offset: int,
    status_filter: str | None,
    q: str | None,
) -> tuple[list[dict[str, object]], int]:
    report_ranges = _report_range_subquery()
    stmt = (
        select(
            EventCluster,
            report_ranges.c.report_start_at,
            report_ranges.c.report_end_at,
        )
        .outerjoin(report_ranges, report_ranges.c.event_cluster_id == EventCluster.id)
        .order_by(
        EventCluster.final_score.desc(), EventCluster.created_at.desc()
        )
    )
    if status_filter:
        stmt = stmt.where(EventCluster.status == status_filter)
    if q:
        stmt = stmt.where(EventCluster.canonical_headline.ilike(f"%{q}%"))
    total = await count_for(session, stmt)
    rows = list((await session.execute(apply_pagination(stmt, limit=limit, offset=offset))).all())
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


def _report_range_subquery():
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
