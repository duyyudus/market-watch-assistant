from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api_server.app.schemas import (
    AlertChannelCreate,
    AlertChannelRead,
    AlertChannelUpdate,
    AlertRead,
    AlertSuppressionRuleCreate,
    AlertSuppressionRuleRead,
    AlertSuppressionRuleUpdate,
    BotCommandRead,
)
from api_server.app.services.query import apply_pagination, count_for
from common.db.models import (
    AlertChannel,
    AlertSuppressionRule,
    BotCommand,
    EventCluster,
)
from common.db.models import (
    AlertDecisionRecord as AlertDecision,
)
from common.db.models import (
    AlertDeliveryRecord as AlertDelivery,
)


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


async def acknowledge_alert(session: AsyncSession, alert_id: str) -> AlertRead | None:
    alert = await session.get(AlertDecision, alert_id)
    if alert is None:
        return None
    alert.acknowledged_at = datetime.now(UTC)
    await session.flush()
    return await get_alert_detail(session, alert_id)


async def dismiss_alert(session: AsyncSession, alert_id: str) -> AlertRead | None:
    alert = await session.get(AlertDecision, alert_id)
    if alert is None:
        return None
    alert.suppression_reason = "dismissed"
    alert.acknowledged_at = alert.acknowledged_at or datetime.now(UTC)
    await session.flush()
    return await get_alert_detail(session, alert_id)


async def list_channels(session: AsyncSession) -> tuple[list[AlertChannelRead], int]:
    rows = list(
        (
            await session.scalars(
                select(AlertChannel).order_by(AlertChannel.is_default.desc(), AlertChannel.name)
            )
        ).all()
    )
    return [AlertChannelRead(**row.__dict__) for row in rows], len(rows)


async def create_channel(
    session: AsyncSession,
    payload: AlertChannelCreate,
) -> AlertChannelRead:
    _validate_channel(payload.channel_type, payload.config)
    row = AlertChannel(**payload.model_dump())
    session.add(row)
    await session.flush()
    await session.refresh(row)
    return AlertChannelRead(**row.__dict__)


async def update_channel(
    session: AsyncSession,
    channel_id: str,
    payload: AlertChannelUpdate,
) -> AlertChannelRead | None:
    row = await session.get(AlertChannel, channel_id)
    if row is None:
        return None
    data = payload.model_dump(exclude_unset=True)
    channel_type = str(data.get("channel_type", row.channel_type))
    config = data.get("config", row.config)
    _validate_channel(channel_type, config)
    for key, value in data.items():
        setattr(row, key, value)
    await session.flush()
    await session.refresh(row)
    return AlertChannelRead(**row.__dict__)


async def delete_channel(session: AsyncSession, channel_id: str) -> bool:
    row = await session.get(AlertChannel, channel_id)
    if row is None:
        return False
    await session.delete(row)
    await session.flush()
    return True


async def queue_channel_test(
    session: AsyncSession,
    channel_id: str,
    message: str,
) -> BotCommandRead | None:
    row = await session.get(AlertChannel, channel_id)
    if row is None:
        return None
    command = BotCommand(
        command_type="alert.test_channel",
        payload={"channel_id": channel_id, "message": message},
        requested_by="dashboard",
    )
    session.add(command)
    await session.flush()
    await session.refresh(command)
    return BotCommandRead(**command.__dict__)


async def list_suppression_rules(
    session: AsyncSession,
) -> tuple[list[AlertSuppressionRuleRead], int]:
    rows = list(
        (
            await session.scalars(
                select(AlertSuppressionRule).order_by(AlertSuppressionRule.created_at.desc())
            )
        ).all()
    )
    return [AlertSuppressionRuleRead(**row.__dict__) for row in rows], len(rows)


async def create_suppression_rule(
    session: AsyncSession,
    payload: AlertSuppressionRuleCreate,
) -> AlertSuppressionRuleRead:
    _validate_rule(payload.rule_type)
    row = AlertSuppressionRule(**payload.model_dump())
    session.add(row)
    await session.flush()
    await session.refresh(row)
    return AlertSuppressionRuleRead(**row.__dict__)


async def update_suppression_rule(
    session: AsyncSession,
    rule_id: str,
    payload: AlertSuppressionRuleUpdate,
) -> AlertSuppressionRuleRead | None:
    row = await session.get(AlertSuppressionRule, rule_id)
    if row is None:
        return None
    data = payload.model_dump(exclude_unset=True)
    _validate_rule(str(data.get("rule_type", row.rule_type)))
    for key, value in data.items():
        setattr(row, key, value)
    await session.flush()
    await session.refresh(row)
    return AlertSuppressionRuleRead(**row.__dict__)


async def delete_suppression_rule(session: AsyncSession, rule_id: str) -> bool:
    row = await session.get(AlertSuppressionRule, rule_id)
    if row is None:
        return False
    await session.delete(row)
    await session.flush()
    return True


def _validate_channel(channel_type: str, config: dict[str, object]) -> None:
    if channel_type not in {"log", "telegram", "webhook", "email", "slack"}:
        raise ValueError(f"Unsupported alert channel type: {channel_type}")
    if channel_type == "webhook" and not str(config.get("url") or "").startswith(("http://", "https://")):
        raise ValueError("Webhook channel requires an http(s) url")


def _validate_rule(rule_type: str) -> None:
    if rule_type not in {"cooldown", "region_filter", "quiet_hours", "entity_mute"}:
        raise ValueError(f"Unsupported suppression rule type: {rule_type}")
