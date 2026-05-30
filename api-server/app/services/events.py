from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AgentInvestigation, AlertDecision, EventCluster, EventScoreHistory
from app.schemas import AlertRead, EventRead
from app.services.query import apply_pagination, count_for


async def list_events(
    session: AsyncSession,
    *,
    limit: int,
    offset: int,
    status_filter: str | None,
    q: str | None,
) -> tuple[list[EventCluster], int]:
    stmt = select(EventCluster).order_by(
        EventCluster.final_score.desc(), EventCluster.created_at.desc()
    )
    if status_filter:
        stmt = stmt.where(EventCluster.status == status_filter)
    if q:
        stmt = stmt.where(EventCluster.canonical_headline.ilike(f"%{q}%"))
    total = await count_for(session, stmt)
    rows = list((await session.scalars(apply_pagination(stmt, limit=limit, offset=offset))).all())
    return rows, total


async def get_event_detail(session: AsyncSession, event: EventCluster) -> dict[str, object]:
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
    return {
        **EventRead.model_validate(event).model_dump(),
        "latest_alert": (
            AlertRead(
                **latest_alert.__dict__,
                event={"id": event.id, "headline": event.canonical_headline},
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
    }


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
