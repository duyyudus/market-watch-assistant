from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AlertDecision, AlertDelivery, EventCluster
from app.schemas import AlertRead
from app.services.query import apply_pagination, count_for


async def list_alerts(
    session: AsyncSession,
    *,
    limit: int,
    offset: int,
    level: str | None,
) -> tuple[list[AlertRead], int]:
    stmt = (
        select(AlertDecision, EventCluster)
        .join(EventCluster, EventCluster.id == AlertDecision.event_cluster_id)
        .order_by(AlertDecision.created_at.desc())
    )
    if level:
        stmt = stmt.where(AlertDecision.decision == level)
    total = await count_for(session, stmt)
    rows = list((await session.execute(apply_pagination(stmt, limit=limit, offset=offset))).all())
    return (
        [
            AlertRead(
                **alert.__dict__,
                event={
                    "id": event.id,
                    "headline": event.canonical_headline,
                    "final_score": event.final_score,
                    "status": event.status,
                },
            )
            for alert, event in rows
        ],
        total,
    )


async def get_alert_detail(session: AsyncSession, alert_id: str) -> AlertRead | None:
    row = (
        await session.execute(
            select(AlertDecision, EventCluster)
            .join(EventCluster, EventCluster.id == AlertDecision.event_cluster_id)
            .where(AlertDecision.id == alert_id)
        )
    ).first()
    if row is None:
        return None
    alert, event = row
    delivery = await session.scalar(
        select(AlertDelivery)
        .where(AlertDelivery.alert_decision_id == alert.id)
        .order_by(AlertDelivery.created_at.desc())
        .limit(1)
    )
    return AlertRead(
        **alert.__dict__,
        event={
            "id": event.id,
            "headline": event.canonical_headline,
            "final_score": event.final_score,
        },
        latest_delivery_status=delivery.status if delivery else None,
        latest_delivery_error=delivery.error_message if delivery else None,
    )
