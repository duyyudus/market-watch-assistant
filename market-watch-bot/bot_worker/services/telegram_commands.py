from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Any

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot_worker.db.models import (
    AlertDecisionRecord,
    AlertDeliveryRecord,
    AppSetting,
    EventCluster,
    EventClusterItem,
    NormalizedNewsItem,
)
from bot_worker.services.alert_delivery import AlertDeliveryConfig

TELEGRAM_COMMAND_OFFSET_KEY = "telegram.command_offset"
DETAIL_REQUIRES_REPLY = "Reply to an alert message with /detail."
DETAIL_UNKNOWN_ALERT = "I could not find an alert for that message."
DETAIL_NO_ARTICLES = "No related articles were found for this alert."
TELEGRAM_BOT_COMMANDS = [
    {
        "command": "detail",
        "description": "Show article titles and URLs for a replied alert",
    }
]

TelegramUpdatesFetcher = Callable[
    [AlertDeliveryConfig, int | None],
    Awaitable[list[dict[str, Any]]],
]
TelegramReplySender = Callable[
    [AlertDeliveryConfig, str, str, int | None],
    Awaitable[dict[str, Any]],
]
ProcessCounts = dict[str, int]


@dataclass(frozen=True)
class AlertDetail:
    alert: AlertDecisionRecord
    event: EventCluster
    articles: list[NormalizedNewsItem]


async def fetch_telegram_updates(
    config: AlertDeliveryConfig,
    offset: int | None,
) -> list[dict[str, Any]]:
    if not config.telegram_bot_token:
        raise ValueError("Telegram command polling requires TELEGRAM_BOT_TOKEN")
    url = f"https://api.telegram.org/bot{config.telegram_bot_token}/getUpdates"
    params: dict[str, object] = {"timeout": 0, "allowed_updates": '["message"]'}
    if offset is not None:
        params["offset"] = offset
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.get(url, params=params)
        response.raise_for_status()
        data = response.json()
    if not data.get("ok"):
        description = data.get("description") or "Telegram getUpdates returned ok=false"
        raise RuntimeError(str(description))
    result = data.get("result") or []
    if not isinstance(result, list):
        return []
    return [item for item in result if isinstance(item, dict)]


async def send_telegram_reply(
    config: AlertDeliveryConfig,
    chat_id: str,
    message: str,
    reply_to_message_id: int | None,
) -> dict[str, Any]:
    if not config.telegram_bot_token:
        raise ValueError("Telegram command replies require TELEGRAM_BOT_TOKEN")
    url = f"https://api.telegram.org/bot{config.telegram_bot_token}/sendMessage"
    payload: dict[str, object] = {
        "chat_id": chat_id,
        "text": message,
        "disable_web_page_preview": True,
    }
    if reply_to_message_id is not None:
        payload["reply_to_message_id"] = reply_to_message_id
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(url, json=payload)
        response.raise_for_status()
        data = response.json()
    if not data.get("ok"):
        description = data.get("description") or "Telegram sendMessage returned ok=false"
        raise RuntimeError(str(description))
    return data


async def register_telegram_bot_commands(config: AlertDeliveryConfig) -> dict[str, Any]:
    if not config.telegram_bot_token:
        raise ValueError("Telegram command registration requires TELEGRAM_BOT_TOKEN")
    url = f"https://api.telegram.org/bot{config.telegram_bot_token}/setMyCommands"
    payload: dict[str, object] = {"commands": TELEGRAM_BOT_COMMANDS}
    if config.telegram_chat_id:
        payload["scope"] = {"type": "chat", "chat_id": config.telegram_chat_id}
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(url, json=payload)
        response.raise_for_status()
        data = response.json()
    if not data.get("ok"):
        description = data.get("description") or "Telegram setMyCommands returned ok=false"
        raise RuntimeError(str(description))
    return data


async def poll_telegram_commands(
    session: AsyncSession,
    config: AlertDeliveryConfig,
    *,
    article_limit: int = 10,
    fetch_updates: TelegramUpdatesFetcher = fetch_telegram_updates,
    send_reply: TelegramReplySender = send_telegram_reply,
) -> ProcessCounts:
    if not config.telegram_configured:
        return {"updates": 0, "processed": 0, "ignored": 0, "replied": 0}
    offset = await telegram_command_offset(session)
    updates = await fetch_updates(config, offset)
    return await process_telegram_updates(
        session,
        config,
        updates,
        article_limit=article_limit,
        send_reply=send_reply,
    )


async def process_telegram_updates(
    session: AsyncSession,
    config: AlertDeliveryConfig,
    updates: Sequence[dict[str, Any]],
    *,
    article_limit: int = 10,
    send_reply: TelegramReplySender = send_telegram_reply,
) -> ProcessCounts:
    counts = {"updates": len(updates), "processed": 0, "ignored": 0, "replied": 0, "failed": 0}
    for update in updates:
        update_id = _int_or_none(update.get("update_id"))
        message = update.get("message")
        if not isinstance(message, dict):
            counts["ignored"] += 1
            if update_id is not None:
                await set_telegram_command_offset(session, update_id + 1)
            continue
        chat_id = _chat_id(message)
        text = str(message.get("text") or "").strip()
        if chat_id != str(config.telegram_chat_id) or _command_name(text) != "/detail":
            counts["ignored"] += 1
            if update_id is not None:
                await set_telegram_command_offset(session, update_id + 1)
            continue
        counts["processed"] += 1
        reply_message = await _detail_reply_message(session, message, article_limit=article_limit)
        try:
            await send_reply(
                config,
                chat_id,
                reply_message,
                _int_or_none(message.get("message_id")),
            )
        except Exception:  # noqa: BLE001 - one failed reply must not replay earlier updates
            counts["failed"] += 1
        else:
            counts["replied"] += 1
        if update_id is not None:
            await set_telegram_command_offset(session, update_id + 1)
    return counts


async def telegram_command_offset(session: AsyncSession) -> int | None:
    setting = await session.get(AppSetting, TELEGRAM_COMMAND_OFFSET_KEY)
    if setting is None or not isinstance(setting.value, dict):
        return None
    return _int_or_none(setting.value.get("offset"))


async def set_telegram_command_offset(session: AsyncSession, offset: int) -> None:
    value = {"offset": offset}
    setting = await session.get(AppSetting, TELEGRAM_COMMAND_OFFSET_KEY)
    if setting is None:
        session.add(AppSetting(key=TELEGRAM_COMMAND_OFFSET_KEY, value=value))
        return
    setting.value = value


async def _detail_reply_message(
    session: AsyncSession,
    message: dict[str, Any],
    *,
    article_limit: int,
) -> str:
    reply_to_message = message.get("reply_to_message")
    if not isinstance(reply_to_message, dict):
        return DETAIL_REQUIRES_REPLY
    replied_message_id = _int_or_none(reply_to_message.get("message_id"))
    if replied_message_id is None:
        return DETAIL_REQUIRES_REPLY
    detail = await find_alert_detail_for_telegram_message(
        session,
        telegram_message_id=replied_message_id,
        chat_id=_chat_id(message),
        article_limit=article_limit,
    )
    if detail is None:
        return DETAIL_UNKNOWN_ALERT
    if not detail.articles:
        return DETAIL_NO_ARTICLES
    return format_alert_detail_message(
        detail.alert,
        detail.event,
        detail.articles,
        article_limit=article_limit,
    )


async def find_alert_detail_for_telegram_message(
    session: AsyncSession,
    *,
    telegram_message_id: int,
    chat_id: str,
    article_limit: int = 10,
) -> AlertDetail | None:
    message_id_expr = AlertDeliveryRecord.provider_response["result"]["message_id"].as_integer()
    delivery = await session.scalars(
        select(AlertDeliveryRecord)
        .where(
            AlertDeliveryRecord.channel == "telegram",
            AlertDeliveryRecord.status == "sent",
            AlertDeliveryRecord.alert_decision_id.is_not(None),
            AlertDeliveryRecord.recipient == chat_id,
            message_id_expr == telegram_message_id,
        )
        .order_by(AlertDeliveryRecord.created_at.desc())
        .limit(1)
    )
    delivery_record = delivery.first()
    if delivery_record is None:
        return None
    if delivery_record.recipient != chat_id:
        return None
    response = (
        delivery_record.provider_response
        if isinstance(delivery_record.provider_response, dict)
        else {}
    )
    if _provider_message_id(response) != telegram_message_id:
        return None
    row = (
        await session.execute(
            select(AlertDecisionRecord, EventCluster)
            .join(EventCluster, EventCluster.id == AlertDecisionRecord.event_cluster_id)
            .where(AlertDecisionRecord.id == delivery_record.alert_decision_id)
            .limit(1)
        )
    ).first()
    if row is None:
        return None
    alert, event = row
    articles = await _articles_for_event(session, event.id, limit=article_limit)
    return AlertDetail(alert=alert, event=event, articles=articles)


async def _articles_for_event(
    session: AsyncSession,
    event_cluster_id: str,
    *,
    limit: int,
) -> list[NormalizedNewsItem]:
    effective_report_time = func.coalesce(
        NormalizedNewsItem.published_at,
        NormalizedNewsItem.fetched_at,
        NormalizedNewsItem.created_at,
    )
    rows = list(
        (
            await session.execute(
                select(NormalizedNewsItem)
                .join(EventClusterItem, EventClusterItem.news_item_id == NormalizedNewsItem.id)
                .where(EventClusterItem.event_cluster_id == event_cluster_id)
                .order_by(effective_report_time.desc())
                .limit(limit)
            )
        ).all()
    )
    return [row[0] for row in rows][:limit]


def format_alert_detail_message(
    alert: AlertDecisionRecord,
    event: EventCluster,
    articles: Sequence[NormalizedNewsItem],
    *,
    article_limit: int = 10,
) -> str:
    lines = [
        "[Alert Detail]",
        "",
        "Event:",
        event.canonical_headline,
        "",
        f"Alert: {alert.id}",
        "",
        "Articles:",
    ]
    for article in list(articles)[:article_limit]:
        lines.append(f"- {article.title}\n  {article.url}")
    return "\n".join(lines)


def _provider_message_id(provider_response: dict[str, Any]) -> int | None:
    result = provider_response.get("result")
    if not isinstance(result, dict):
        return None
    return _int_or_none(result.get("message_id"))


def _chat_id(message: dict[str, Any]) -> str:
    chat = message.get("chat")
    if not isinstance(chat, dict):
        return ""
    return str(chat.get("id") or "")


def _command_name(text: str) -> str:
    if not text:
        return ""
    return text.split(maxsplit=1)[0].split("@", maxsplit=1)[0].lower()


def _int_or_none(value: object) -> int | None:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
