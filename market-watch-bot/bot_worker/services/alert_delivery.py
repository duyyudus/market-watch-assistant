from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot_worker.config import Settings
from bot_worker.db.models import (
    AlertChannel,
    AlertDecisionRecord,
    AlertDeliveryRecord,
    AlertSuppressionRule,
    EventCluster,
)
from bot_worker.services.digests import (
    ReportTimeRange,
    event_report_time_range,
    format_report_time_span,
)

DeliveryCounts = dict[str, int]
TelegramSender = Callable[["AlertDeliveryConfig", str, str], Awaitable[dict[str, Any]]]
WebhookSender = Callable[[str, dict[str, object], dict[str, str]], Awaitable[dict[str, Any]]]
REDACTED_TELEGRAM_TOKEN = "[REDACTED_TELEGRAM_TOKEN]"
MAX_DELIVERY_ATTEMPTS = 3
RETRY_DELAY = timedelta(minutes=5)


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
    if config.channel == "log":
        return None
    if config.channel == "webhook":
        return None
    if config.channel != "telegram":
        return f"Unsupported alert delivery channel: {config.channel}"
    if not config.telegram_configured:
        return "Telegram delivery requires TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID"
    return None


def format_alert_message(
    alert: AlertDecisionRecord,
    event: EventCluster,
    *,
    report_time_range: ReportTimeRange | None = None,
) -> str:
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
    report_time = format_report_time_span(report_time_range)
    if report_time:
        lines.extend(["", "Reports:", report_time])
    lines.extend(["", "Score:", str(event.final_score)])
    lines.extend(["", "Sources:", f"{event.source_count} report(s)"])
    if why_it_matters:
        lines.extend(["", "Why it matters:", why_it_matters])
    elif not alert_message:
        lines.extend(["", "Reason:", alert.reason])
    return "\n".join(lines)


def format_webhook_payload(alert: AlertDecisionRecord, event: EventCluster) -> dict[str, object]:
    return {
        "alert": {
            "id": alert.id,
            "decision": alert.decision,
            "reason": alert.reason,
            "channel": alert.channel,
            "suppression_reason": alert.suppression_reason,
            "sent_at": _iso(alert.sent_at),
            "acknowledged_at": _iso(alert.acknowledged_at),
            "created_at": _iso(alert.created_at),
            "score_breakdown": alert.score_breakdown,
        },
        "event": {
            "id": event.id,
            "headline": event.canonical_headline,
            "status": event.status,
            "regions": event.regions or [],
            "asset_classes": event.asset_classes or [],
            "affected_entities": event.affected_entities or [],
            "affected_tickers": event.affected_tickers or [],
            "source_count": event.source_count,
            "final_score": event.final_score,
        },
    }


def apply_alert_suppression(
    alert: AlertDecisionRecord,
    event: EventCluster,
    rules: Sequence[AlertSuppressionRule],
    *,
    now: datetime | None = None,
) -> str | None:
    current = now or _utcnow()
    for rule in rules:
        if rule.enabled is False:
            continue
        reason = _suppression_reason(rule, event, current)
        if reason:
            alert.suppression_reason = reason
            return reason
    return None


async def send_telegram_message(
    config: AlertDeliveryConfig,
    recipient: str,
    message: str,
) -> dict[str, Any]:
    if not config.telegram_bot_token:
        raise ValueError("Telegram delivery requires TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID")
    url = f"https://api.telegram.org/bot{config.telegram_bot_token}/sendMessage"
    payload = {"chat_id": recipient, "text": message, "disable_web_page_preview": True}
    from bot_worker.services.external_providers import PROVIDER_RETRY_POLICIES, request_with_retry

    async with httpx.AsyncClient(timeout=20) as client:
        response = await request_with_retry(
            provider="telegram",
            method="POST",
            url=url,
            retry_policy=PROVIDER_RETRY_POLICIES["telegram"],
            client=client,
            json=payload,
        )
        data = response.json()
    if not data.get("ok"):
        description = data.get("description") or "Telegram API returned ok=false"
        raise RuntimeError(str(description))
    return data


async def send_webhook_payload(
    url: str,
    payload: dict[str, object],
    headers: dict[str, str],
) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(url, json=payload, headers=headers)
        response.raise_for_status()
        try:
            return response.json()
        except ValueError:
            return {"status_code": response.status_code, "text": response.text[:500]}


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
        error_message = redact_telegram_token(str(exc), config.telegram_bot_token)
        session.add(
            AlertDeliveryRecord(
                channel=config.channel,
                recipient=config.telegram_chat_id,
                status="failed",
                message_text=message,
                error_message=error_message,
                attempted_at=attempted_at,
            )
        )
        return {
            "status": "failed",
            "channel": config.channel,
            "recipient": config.telegram_chat_id,
            "error": error_message,
        }
    session.add(
        AlertDeliveryRecord(
            channel=config.channel,
            recipient=config.telegram_chat_id,
            status="sent",
            message_text=message,
            provider_response=redact_sensitive_payload(
                provider_response,
                config.telegram_bot_token,
            ),
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
    send_webhook_payload: WebhookSender = send_webhook_payload,
    now: datetime | None = None,
) -> DeliveryCounts:
    current = now or _utcnow()
    counts = {
        "pending": 0,
        "attempted": 0,
        "sent": 0,
        "failed": 0,
        "skipped": 0,
    }
    if not dry_run and not config.telegram_configured and config.channel == "telegram":
        return counts
    channel_record = await _default_channel(session, config.channel)
    channel_type = channel_record.channel_type if channel_record else config.channel
    channel_config = channel_record.config if channel_record else {}
    recipient = _recipient_for(channel_type, config, channel_config)

    retry_deliveries = await _retryable_deliveries(session, current, limit)
    for delivery in retry_deliveries:
        if dry_run:
            counts["pending"] += 1
            continue
        counts["attempted"] += 1
        try:
            await _send_delivery_retry(
                delivery,
                config,
                channel_config,
                send_telegram_message=send_telegram_message,
                send_webhook_payload=send_webhook_payload,
            )
        except Exception as exc:
            _mark_delivery_failed(delivery, exc, config, current)
            if delivery.status == "permanently_failed":
                counts["permanently_failed"] = counts.get("permanently_failed", 0) + 1
            else:
                counts["failed"] += 1
            continue
        delivery.status = "sent"
        delivery.error_message = None
        delivery.next_attempt_at = None
        counts["sent"] += 1

    stmt = (
        select(AlertDecisionRecord, EventCluster)
        .join(EventCluster, EventCluster.id == AlertDecisionRecord.event_cluster_id)
        .where(AlertDecisionRecord.sent_at.is_(None))
        .order_by(AlertDecisionRecord.created_at.asc())
        .limit(limit)
    )
    rows = list((await session.execute(stmt)).all())
    rules = await _suppression_rules(session)
    for alert, event in rows:
        if (
            alert.sent_at is not None
            or alert.decision != "immediate_alert"
            or alert.suppression_reason
        ):
            counts["skipped"] += 1
            continue
        apply_alert_suppression(alert, event, rules, now=current)
        if alert.suppression_reason:
            counts["skipped"] += 1
            continue
        counts["pending"] += 1
        report_time_range = await event_report_time_range(session, event.id)
        message = format_alert_message(alert, event, report_time_range=report_time_range)
        if dry_run:
            continue
        counts["attempted"] += 1
        attempted_at = current
        try:
            provider_response = await _send_new_alert(
                channel_type,
                config,
                channel_config,
                recipient,
                alert,
                event,
                message,
                send_telegram_message=send_telegram_message,
                send_webhook_payload=send_webhook_payload,
            )
        except Exception as exc:
            error_message = redact_telegram_token(str(exc), config.telegram_bot_token)
            counts["failed"] += 1
            session.add(
                AlertDeliveryRecord(
                    alert_decision_id=alert.id,
                    channel=channel_type,
                    recipient=recipient,
                    status="failed",
                    message_text=message,
                    error_message=error_message,
                    attempted_at=attempted_at,
                    attempt_count=1,
                    next_attempt_at=attempted_at + RETRY_DELAY,
                )
            )
            continue
        counts["pending"] -= 1
        alert.sent_at = attempted_at
        alert.channel = channel_type
        event.last_alerted_at = attempted_at
        event.alert_level = alert.decision
        counts["sent"] += 1
        session.add(
            AlertDeliveryRecord(
                alert_decision_id=alert.id,
                channel=channel_type,
                recipient=recipient,
                status="sent",
                message_text=message,
                provider_response=redact_sensitive_payload(
                    provider_response,
                    config.telegram_bot_token,
                ),
                attempted_at=attempted_at,
            )
        )
    return counts


async def send_test_alert_to_channel(
    session: AsyncSession,
    channel: AlertChannel,
    config: AlertDeliveryConfig,
    message: str,
    *,
    send_telegram_message: TelegramSender = send_telegram_message,
    send_webhook_payload: WebhookSender = send_webhook_payload,
) -> dict[str, object]:
    attempted_at = _utcnow()
    recipient = _recipient_for(channel.channel_type, config, channel.config)
    try:
        if channel.channel_type == "log":
            provider_response = {"logged": True}
        elif channel.channel_type == "telegram":
            provider_response = await send_telegram_message(config, recipient, message)
        elif channel.channel_type == "webhook":
            url = str(channel.config.get("url") or "")
            provider_response = await send_webhook_payload(
                url,
                {"message": message, "channel_id": channel.id},
                _webhook_headers(channel.config),
            )
        else:
            raise ValueError(f"Unsupported alert delivery channel: {channel.channel_type}")
    except Exception as exc:
        error_message = redact_sensitive_text(str(exc), config.telegram_bot_token)
        session.add(
            AlertDeliveryRecord(
                channel=channel.channel_type,
                recipient=recipient,
                status="failed",
                message_text=message,
                error_message=error_message,
                attempted_at=attempted_at,
                attempt_count=1,
                next_attempt_at=attempted_at + RETRY_DELAY,
            )
        )
        return {"status": "failed", "channel": channel.channel_type, "error": error_message}
    session.add(
        AlertDeliveryRecord(
            channel=channel.channel_type,
            recipient=recipient,
            status="sent",
            message_text=message,
            provider_response=redact_sensitive_payload(
                provider_response,
                config.telegram_bot_token,
            ),
            attempted_at=attempted_at,
        )
    )
    return {"status": "sent", "channel": channel.channel_type, "recipient": recipient}


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


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _suppression_reason(
    rule: AlertSuppressionRule,
    event: EventCluster,
    current: datetime,
) -> str | None:
    config = rule.config or {}
    if rule.rule_type == "cooldown":
        hours = int(config.get("hours", 0) or 0)
        if hours > 0 and event.last_alerted_at:
            last_alerted = event.last_alerted_at
            if last_alerted.tzinfo is None:
                last_alerted = last_alerted.replace(tzinfo=UTC)
            if current - last_alerted <= timedelta(hours=hours):
                return f"cooldown: repeated alert inside {hours}h"
    if rule.rule_type == "quiet_hours":
        timezone = ZoneInfo(str(config.get("timezone") or "Asia/Ho_Chi_Minh"))
        local = current.astimezone(timezone)
        start_hour = int(config.get("start_hour", 23))
        end_hour = int(config.get("end_hour", 7))
        if _hour_in_window(local.hour, start_hour, end_hour):
            return f"quiet_hours: {start_hour}:00-{end_hour}:00"
    if rule.rule_type == "region_filter":
        regions = {str(item) for item in config.get("regions", [])}
        categories = {
            str(item)
            for item in config.get("asset_classes", config.get("categories", []))
        }
        weekend_only = bool(config.get("weekend_only", False))
        if weekend_only and current.weekday() < 5:
            return None
        if regions and regions.intersection(set(event.regions or [])):
            return f"region_filter: {', '.join(sorted(regions))}"
        if categories and categories.intersection(set(event.asset_classes or [])):
            return f"region_filter: {', '.join(sorted(categories))}"
    if rule.rule_type == "entity_mute":
        until = config.get("until")
        if until:
            mute_until = datetime.fromisoformat(str(until)).astimezone(UTC)
            if current > mute_until:
                return None
        muted = {str(item).lower() for item in config.get("entities", [])}
        affected = {
            str(item).lower()
            for item in [*(event.affected_entities or []), *(event.affected_tickers or [])]
        }
        if muted.intersection(affected):
            return "entity_mute: muted entity"
    return None


def _hour_in_window(hour: int, start_hour: int, end_hour: int) -> bool:
    if start_hour < end_hour:
        return start_hour <= hour < end_hour
    return hour >= start_hour or hour < end_hour


async def _default_channel(session: AsyncSession, channel_type: str) -> AlertChannel | None:
    if not hasattr(session, "scalars"):
        return None
    try:
        result = await session.scalars(
            select(AlertChannel)
            .where(AlertChannel.enabled.is_(True), AlertChannel.channel_type == channel_type)
            .order_by(AlertChannel.is_default.desc(), AlertChannel.created_at.asc())
            .limit(1)
        )
        return result.first()
    except Exception:  # noqa: BLE001 - pre-migration deployments should still dispatch settings channels
        await _maybe_rollback(session)
        return None


async def _suppression_rules(session: AsyncSession) -> list[AlertSuppressionRule]:
    if not hasattr(session, "scalars"):
        return []
    try:
        return list(
            (
                await session.scalars(
                    select(AlertSuppressionRule)
                    .where(AlertSuppressionRule.enabled.is_(True))
                    .order_by(AlertSuppressionRule.created_at.asc())
                )
            ).all()
        )
    except Exception:  # noqa: BLE001 - pre-migration deployments should keep dispatching
        await _maybe_rollback(session)
        return []


async def _retryable_deliveries(
    session: AsyncSession,
    current: datetime,
    limit: int,
) -> list[AlertDeliveryRecord]:
    if hasattr(session, "retry_deliveries"):
        return list(session.retry_deliveries)
    if not hasattr(session, "scalars"):
        return []
    try:
        result = await session.scalars(
            select(AlertDeliveryRecord)
            .where(
                AlertDeliveryRecord.status == "failed",
                or_(
                    AlertDeliveryRecord.next_attempt_at.is_(None),
                    AlertDeliveryRecord.next_attempt_at <= current,
                ),
            )
            .order_by(AlertDeliveryRecord.attempted_at.asc())
            .limit(limit)
        )
        return list(result.all())
    except Exception:  # noqa: BLE001 - retry table columns may not be migrated yet
        await _maybe_rollback(session)
        return []


async def _maybe_rollback(session: AsyncSession) -> None:
    rollback = getattr(session, "rollback", None)
    if rollback:
        await rollback()


def _recipient_for(
    channel_type: str,
    config: AlertDeliveryConfig,
    channel_config: dict[str, object],
) -> str:
    if channel_type == "webhook":
        return str(channel_config.get("url") or "")
    if channel_type == "telegram":
        return str(channel_config.get("chat_id") or config.telegram_chat_id or "")
    return channel_type


async def _send_new_alert(
    channel_type: str,
    config: AlertDeliveryConfig,
    channel_config: dict[str, object],
    recipient: str,
    alert: AlertDecisionRecord,
    event: EventCluster,
    message: str,
    *,
    send_telegram_message: TelegramSender,
    send_webhook_payload: WebhookSender,
) -> dict[str, Any]:
    if channel_type == "log":
        return {"logged": True}
    if channel_type == "telegram":
        return await send_telegram_message(config, recipient, message)
    if channel_type == "webhook":
        return await send_webhook_payload(
            recipient,
            format_webhook_payload(alert, event),
            _webhook_headers(channel_config),
        )
    raise ValueError(f"Unsupported alert delivery channel: {channel_type}")


async def _send_delivery_retry(
    delivery: AlertDeliveryRecord,
    config: AlertDeliveryConfig,
    channel_config: dict[str, object],
    *,
    send_telegram_message: TelegramSender,
    send_webhook_payload: WebhookSender,
) -> dict[str, Any]:
    if delivery.channel == "log":
        return {"logged": True}
    if delivery.channel == "telegram":
        return await send_telegram_message(config, delivery.recipient, delivery.message_text)
    if delivery.channel == "webhook":
        return await send_webhook_payload(
            delivery.recipient,
            {"message": delivery.message_text, "retry": True},
            _webhook_headers(channel_config),
        )
    raise ValueError(f"Unsupported alert delivery channel: {delivery.channel}")


def _mark_delivery_failed(
    delivery: AlertDeliveryRecord,
    exc: Exception,
    config: AlertDeliveryConfig,
    current: datetime,
) -> None:
    delivery.attempt_count = int(delivery.attempt_count or 0) + 1
    delivery.attempted_at = current
    delivery.error_message = redact_sensitive_text(str(exc), config.telegram_bot_token)
    if delivery.attempt_count >= MAX_DELIVERY_ATTEMPTS:
        delivery.status = "permanently_failed"
        delivery.permanently_failed_at = current
        delivery.next_attempt_at = None
    else:
        delivery.status = "failed"
        delivery.next_attempt_at = current + RETRY_DELAY


def _webhook_headers(config: dict[str, object]) -> dict[str, str]:
    headers = config.get("headers", {})
    if not isinstance(headers, dict):
        return {}
    return {str(key): str(value) for key, value in headers.items()}


def redact_telegram_token(value: str, token: str | None) -> str:
    if not token:
        return value
    return value.replace(token, REDACTED_TELEGRAM_TOKEN)


def redact_sensitive_text(value: str, token: str | None = None) -> str:
    redacted = redact_telegram_token(value, token)
    for marker in ("Authorization", "authorization", "token", "secret"):
        redacted = redacted.replace(marker, "[REDACTED]")
    return redacted


def redact_sensitive_payload(value: Any, token: str | None) -> Any:
    if token is None:
        return value
    if isinstance(value, str):
        return redact_telegram_token(value, token)
    if isinstance(value, list):
        return [redact_sensitive_payload(item, token) for item in value]
    if isinstance(value, tuple):
        return [redact_sensitive_payload(item, token) for item in value]
    if isinstance(value, dict):
        return {
            str(key): redact_sensitive_payload(item, token)
            for key, item in value.items()
        }
    return value
