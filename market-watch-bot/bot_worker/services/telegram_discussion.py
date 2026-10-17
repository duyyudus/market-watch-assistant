from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from bot_worker.db.models import AppSetting
from common.db.models import utcnow
from common.discussion import AUTO_TIMEFRAME, TIMEFRAMES, DiscussionMessage

TELEGRAM_DISCUSSION_KEY = "telegram.discussion"
# Source times are shown in UTC unless the worker passes bot.timezone.
DEFAULT_TIMEZONE = ZoneInfo("UTC")
# Matches the dashboard chat box, which also starts on Auto.
DEFAULT_TIMEFRAME = AUTO_TIMEFRAME
TIMEFRAME_LABELS = {
    "auto": "Auto (from your question; last 24 hours if it names no period)",
    "24h": "last 24 hours",
    "3d": "last 3 days",
    "7d": "last 7 days",
    "30d": "last 30 days",
    "max": "Max (the longest configured window)",
}
# A quick chat left idle this long starts over, so an old topic does not skew retrieval.
DISCUSSION_IDLE_RESET = timedelta(hours=1)
DISCUSSION_MESSAGE_LIMIT = 20
DISCUSSION_CONTEXT_CHARACTER_LIMIT = 56_000
TELEGRAM_MESSAGE_CHARACTER_LIMIT = 4096
# Auto window sources worth keeping for follow-ups, as in the dashboard chat box.
CARRIED_WINDOW_SOURCES = {"inferred", "carried"}

NEW_CHAT_MESSAGE = "Started a new chat."
DISCUSSION_UNAVAILABLE = "Discussion is unavailable right now."

# The window the chat's previous answer searched: (start, end); end None means up to now.
DiscussionWindow = tuple[datetime, datetime | None]
DiscussionAnswerer = Callable[
    [AsyncSession, str, list[DiscussionMessage], DiscussionWindow | None],
    Awaitable[dict[str, Any]],
]


@dataclass(frozen=True)
class TelegramDiscussion:
    timeframe: str
    messages: list[DiscussionMessage]
    previous_window: DiscussionWindow | None = None


async def answer_telegram_question(
    session: AsyncSession,
    question: str,
    *,
    answer_question: DiscussionAnswerer,
    timezone: ZoneInfo = DEFAULT_TIMEZONE,
) -> str:
    discussion = await _load_discussion(session)
    messages = _request_messages(discussion.messages, question)
    try:
        result = await answer_question(
            session, discussion.timeframe, messages, discussion.previous_window
        )
    except ValueError as exc:
        return str(exc)
    except Exception:  # noqa: BLE001 - a failed answer must not replay the update
        return DISCUSSION_UNAVAILABLE
    answer = str(result.get("answer") or "")
    context_window = result.get("context_window")
    await _save_discussion(
        session,
        TelegramDiscussion(
            timeframe=discussion.timeframe,
            messages=[*messages, {"role": "assistant", "content": answer}][
                -DISCUSSION_MESSAGE_LIMIT:
            ],
            previous_window=_carried_window(context_window),
        ),
    )
    return format_discussion_reply(
        answer, result.get("sources") or [], context_window, timezone=timezone
    )


async def start_new_telegram_chat(session: AsyncSession) -> str:
    discussion = await _load_discussion(session)
    await _save_discussion(session, TelegramDiscussion(discussion.timeframe, []))
    return f"{NEW_CHAT_MESSAGE} Article context: {TIMEFRAME_LABELS[discussion.timeframe]}."


async def set_telegram_discussion_timeframe(session: AsyncSession, value: str) -> str:
    choices = ", ".join(TIMEFRAMES)
    discussion = await _load_discussion(session)
    requested = value.strip().lower()
    if not requested:
        return (
            f"Article context: {TIMEFRAME_LABELS[discussion.timeframe]}. "
            f"Change it with /timeframe <{choices}>."
        )
    if requested not in TIMEFRAMES:
        return f"Unknown timeframe. Choose one of: {choices}."
    # Like the dashboard panel, switching the article window starts a new chat.
    await _save_discussion(session, TelegramDiscussion(requested, []))
    return f"{NEW_CHAT_MESSAGE} Article context: {TIMEFRAME_LABELS[requested]}."


def format_discussion_reply(
    answer: str,
    sources: list[dict[str, Any]],
    context_window: dict[str, Any] | None = None,
    *,
    timezone: ZoneInfo = DEFAULT_TIMEZONE,
) -> str:
    lines = [markdown_to_plain_text(answer)]
    caption = _window_caption(context_window)
    if caption:
        lines.extend(["", caption])
    if sources:
        lines.extend(["", "Sources:"])
        for source in sources:
            # Same "title · outlet · date" line as the dashboard chat box.
            details = [str(source["title"]), str(source["source_name"])]
            published_at = _datetime_or_none(source.get("published_at"))
            if published_at is not None:
                details.append(_format_source_time(published_at, timezone))
            lines.append(f"• {' · '.join(details)}\n  {source['url']}")
    return "\n".join(lines)


def _format_source_time(value: datetime, timezone: ZoneInfo) -> str:
    aware = value if value.tzinfo else value.replace(tzinfo=UTC)
    return f"{aware.astimezone(timezone):%b %d, %H:%M}"


def _window_caption(context_window: dict[str, Any] | None) -> str | None:
    """Same caption as the dashboard: shown when Auto picked the window."""
    if not context_window or context_window.get("source") == "selected":
        return None
    caption = f"Searched {context_window.get('label')}"
    if context_window.get("source") == "inferred":
        caption += " · from your question"
    elif context_window.get("source") == "carried":
        caption += " · same as previous answer"
    return caption


def markdown_to_plain_text(value: str) -> str:
    """Flatten the model's Markdown answer; replies are sent without a parse mode."""
    text = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", r"\1 (\2)", value)
    text = re.sub(r"^\s{0,3}#{1,6}\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"^(\s*)[-*]\s+", "\\1• ", text, flags=re.MULTILINE)
    text = re.sub(r"\*\*(.+?)\*\*|__(.+?)__", lambda match: match[1] or match[2], text)
    # Whole-line italics, e.g. the timeframe notes appended to answers.
    text = re.sub(r"^_(.+)_$", r"\1", text, flags=re.MULTILINE)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    return text.strip()


def split_telegram_message(message: str) -> list[str]:
    chunks: list[str] = []
    remaining = message
    while len(remaining) > TELEGRAM_MESSAGE_CHARACTER_LIMIT:
        cut = remaining.rfind("\n", 0, TELEGRAM_MESSAGE_CHARACTER_LIMIT)
        if cut <= 0:
            cut = TELEGRAM_MESSAGE_CHARACTER_LIMIT
        chunks.append(remaining[:cut].rstrip())
        remaining = remaining[cut:].lstrip("\n")
    if remaining:
        chunks.append(remaining)
    return chunks


def _request_messages(history: list[DiscussionMessage], question: str) -> list[DiscussionMessage]:
    newest_first: list[DiscussionMessage] = [{"role": "user", "content": question}]
    remaining = DISCUSSION_CONTEXT_CHARACTER_LIMIT - len(question)
    for message in reversed(history):
        if len(newest_first) >= DISCUSSION_MESSAGE_LIMIT or remaining <= 0:
            break
        content = message["content"][:remaining]
        if not content:
            continue
        newest_first.append({"role": message["role"], "content": content})
        remaining -= len(content)
    return newest_first[::-1]


def _carried_window(context_window: object) -> DiscussionWindow | None:
    if not isinstance(context_window, dict):
        return None
    if context_window.get("source") not in CARRIED_WINDOW_SOURCES:
        return None
    start = _datetime_or_none(context_window.get("start"))
    if start is None:
        return None
    return start, _datetime_or_none(context_window.get("end"))


def _datetime_or_none(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value)) if value else None
    except ValueError:
        return None


async def _load_discussion(session: AsyncSession) -> TelegramDiscussion:
    setting = await session.get(AppSetting, TELEGRAM_DISCUSSION_KEY)
    value = setting.value if setting is not None and isinstance(setting.value, dict) else {}
    timeframe = value.get("timeframe")
    if timeframe not in TIMEFRAMES:
        timeframe = DEFAULT_TIMEFRAME
    if _is_idle(value.get("last_message_at")):
        return TelegramDiscussion(timeframe, [])
    messages = [
        {"role": str(message["role"]), "content": str(message["content"])}
        for message in value.get("messages") or []
        if isinstance(message, dict) and message.get("role") and message.get("content")
    ]
    previous = value.get("previous_window")
    previous_window = (
        _carried_window({**previous, "source": "carried"}) if isinstance(previous, dict) else None
    )
    return TelegramDiscussion(timeframe, messages, previous_window)


async def _save_discussion(session: AsyncSession, discussion: TelegramDiscussion) -> None:
    value: dict[str, object] = {
        "timeframe": discussion.timeframe,
        "messages": discussion.messages,
        "last_message_at": utcnow().isoformat(),
    }
    if discussion.previous_window is not None:
        start, end = discussion.previous_window
        value["previous_window"] = {
            "start": start.isoformat(),
            "end": end.isoformat() if end else None,
        }
    setting = await session.get(AppSetting, TELEGRAM_DISCUSSION_KEY)
    if setting is None:
        session.add(AppSetting(key=TELEGRAM_DISCUSSION_KEY, value=value))
        return
    setting.value = value


def _is_idle(last_message_at: object) -> bool:
    try:
        last = datetime.fromisoformat(str(last_message_at))
    except ValueError:
        return True
    return utcnow() - last > DISCUSSION_IDLE_RESET
