from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot_worker.config import Settings
from bot_worker.db.models import AlertDecisionRecord, AlertDeliveryRecord, EventCluster

DeliveryCounts = dict[str, int]
TelegramSender = Callable[["AlertDeliveryConfig", str, str], Awaitable[dict[str, Any]]]


@dataclass(frozen=True)
class AlertDeliveryConfig:
    channel: str = "log"
    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None

    @classmethod
    def from_settings(
        cls,
        settings: Settings,
        *,
        channel: str | None = None,
    ) -> AlertDeliveryConfig:
        return cls(
            channel=channel or settings.alerts.default_channel,
            telegram_bot_token=settings.telegram_bot_token,
            telegram_chat_id=settings.telegram_chat_id,
        )

    @property
    def telegram_configured(self) -> bool:
        return bool(self.telegram_bot_token and self.telegram_chat_id)


def delivery_config_error(config: AlertDeliveryConfig) -> str | None:
    if config.channel != "telegram":
        return f"Unsupported alert delivery channel: {config.channel}"
    if not config.telegram_configured:
        return "Telegram delivery requires TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID"
    return None


def format_alert_message(alert: AlertDecisionRecord, event: EventCluster) -> str:
    llm = alert.score_breakdown.get("llm") if isinstance(alert.score_breakdown, dict) else None
    llm_data = llm if isinstance(llm, dict) else {}
    alert_message = str(llm_data.get("alert_message") or "").strip()
    why_it_matters = str(llm_data.get("why_it_matters") or "").strip()
    affected = _join_unique(
        [
            *(event.affected_entities or []),
            *(event.affected_tickers or []),
        ]
    )

    lines = [
        "[Immediate Market Alert]",
        "",
        "Event:",
        alert_message or event.canonical_headline,
        "",
        "Status:",
        event.status,
    ]
    if affected:
        lines.extend(["", "Affected:", affected])
    lines.extend(["", "Score:", str(event.final_score)])
    lines.extend(["", "Sources:", f"{event.source_count} report(s)"])
    if why_it_matters:
        lines.extend(["", "Why it matters:", why_it_matters])
    elif not alert_message:
        lines.extend(["", "Reason:", alert.reason])
    return "\n".join(lines)


async def send_telegram_message(
    config: AlertDeliveryConfig,
    recipient: str,
    message: str,
) -> dict[str, Any]:
    if not config.telegram_bot_token:
        raise ValueError("Telegram delivery requires TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID")
    url = f"https://api.telegram.org/bot{config.telegram_bot_token}/sendMessage"
    payload = {"chat_id": recipient, "text": message, "disable_web_page_preview": True}
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(url, json=payload)
        response.raise_for_status()
        data = response.json()
    if not data.get("ok"):
        description = data.get("description") or "Telegram API returned ok=false"
        raise RuntimeError(str(description))
    return data


async def send_test_alert(
    session: AsyncSession,
    config: AlertDeliveryConfig,
    message: str,
    *,
    send_telegram_message: TelegramSender = send_telegram_message,
) -> dict[str, object]:
    error = delivery_config_error(config)
    if error:
        raise ValueError(error)
    assert config.telegram_chat_id is not None
    attempted_at = _utcnow()
    try:
        provider_response = await send_telegram_message(config, config.telegram_chat_id, message)
    except Exception as exc:
        session.add(
            AlertDeliveryRecord(
                channel=config.channel,
                recipient=config.telegram_chat_id,
                status="failed",
                message_text=message,
                error_message=str(exc),
                attempted_at=attempted_at,
            )
        )
        return {
            "status": "failed",
            "channel": config.channel,
            "recipient": config.telegram_chat_id,
            "error": str(exc),
        }
    session.add(
        AlertDeliveryRecord(
            channel=config.channel,
            recipient=config.telegram_chat_id,
            status="sent",
            message_text=message,
            provider_response=provider_response,
            attempted_at=attempted_at,
        )
    )
    return {"status": "sent", "channel": config.channel, "recipient": config.telegram_chat_id}


async def dispatch_pending_alerts(
    session: AsyncSession,
    config: AlertDeliveryConfig,
    *,
    limit: int = 20,
    dry_run: bool = False,
    send_telegram_message: TelegramSender = send_telegram_message,
) -> DeliveryCounts:
    counts = {"pending": 0, "attempted": 0, "sent": 0, "failed": 0, "skipped": 0}
    if config.channel != "telegram":
        return counts
    if not dry_run and not config.telegram_configured:
        return counts
    recipient = config.telegram_chat_id or ""

    stmt = (
        select(AlertDecisionRecord, EventCluster)
        .join(EventCluster, EventCluster.id == AlertDecisionRecord.event_cluster_id)
        .where(AlertDecisionRecord.sent_at.is_(None))
        .order_by(AlertDecisionRecord.created_at.asc())
        .limit(limit)
    )
    rows = list((await session.execute(stmt)).all())
    for alert, event in rows:
        if (
            alert.sent_at is not None
            or alert.decision != "immediate_alert"
            or alert.suppression_reason
        ):
            counts["skipped"] += 1
            continue
        counts["pending"] += 1
        message = format_alert_message(alert, event)
        if dry_run:
            continue
        counts["attempted"] += 1
        attempted_at = _utcnow()
        try:
            provider_response = await send_telegram_message(config, recipient, message)
        except Exception as exc:
            counts["failed"] += 1
            session.add(
                AlertDeliveryRecord(
                    alert_decision_id=alert.id,
                    channel=config.channel,
                    recipient=recipient,
                    status="failed",
                    message_text=message,
                    error_message=str(exc),
                    attempted_at=attempted_at,
                )
            )
            continue
        counts["pending"] -= 1
        alert.sent_at = attempted_at
        alert.channel = config.channel
        event.last_alerted_at = attempted_at
        event.alert_level = alert.decision
        counts["sent"] += 1
        session.add(
            AlertDeliveryRecord(
                alert_decision_id=alert.id,
                channel=config.channel,
                recipient=recipient,
                status="sent",
                message_text=message,
                provider_response=provider_response,
                attempted_at=attempted_at,
            )
        )
    return counts


def _join_unique(values: list[str]) -> str:
    seen = set()
    result = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return ", ".join(result)


def _utcnow() -> datetime:
    return datetime.now(UTC)
