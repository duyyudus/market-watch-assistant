from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from bot_worker.db.models import AppSetting
from common.db.models import utcnow
from common.discussion import TIMEFRAME_HOURS, DiscussionMessage

TELEGRAM_DISCUSSION_KEY = "telegram.discussion"
DEFAULT_TIMEFRAME = "24h"
# A quick chat left idle this long starts over, so an old topic does not skew retrieval.
DISCUSSION_IDLE_RESET = timedelta(hours=1)
DISCUSSION_MESSAGE_LIMIT = 20
DISCUSSION_CONTEXT_CHARACTER_LIMIT = 56_000
TELEGRAM_MESSAGE_CHARACTER_LIMIT = 4096

ASK_USAGE = "Send a question after /ask, e.g. /ask What moved oil today?"
NEW_CHAT_MESSAGE = "Started a new chat."
DISCUSSION_UNAVAILABLE = "Discussion is unavailable right now."

DiscussionAnswerer = Callable[
    [AsyncSession, str, list[DiscussionMessage]],
    Awaitable[dict[str, Any]],
]


async def answer_telegram_question(
    session: AsyncSession,
    question: str,
    *,
    answer_question: DiscussionAnswerer,
) -> str:
    timeframe, history = await _load_discussion(session)
    messages = _request_messages(history, question)
    try:
        result = await answer_question(session, timeframe, messages)
    except ValueError as exc:
        return str(exc)
    except Exception:  # noqa: BLE001 - a failed answer must not replay the update
        return DISCUSSION_UNAVAILABLE
    answer = str(result.get("answer") or "")
    await _save_discussion(
        session,
        timeframe,
        [*messages, {"role": "assistant", "content": answer}][-DISCUSSION_MESSAGE_LIMIT:],
    )
    return format_discussion_reply(answer, result.get("sources") or [])


async def start_new_telegram_chat(session: AsyncSession) -> str:
    timeframe, _history = await _load_discussion(session)
    await _save_discussion(session, timeframe, [])
    return f"{NEW_CHAT_MESSAGE} Article context: last {timeframe}."


async def set_telegram_discussion_timeframe(session: AsyncSession, value: str) -> str:
    choices = ", ".join(TIMEFRAME_HOURS)
    timeframe, _history = await _load_discussion(session)
    requested = value.strip().lower()
    if not requested:
        return f"Article context: last {timeframe}. Change it with /timeframe <{choices}>."
    if requested not in TIMEFRAME_HOURS:
        return f"Unknown timeframe. Choose one of: {choices}."
    # Like the dashboard panel, switching the article window starts a new chat.
    await _save_discussion(session, requested, [])
    return f"{NEW_CHAT_MESSAGE} Article context: last {requested}."


def format_discussion_reply(answer: str, sources: list[dict[str, Any]]) -> str:
    lines = [markdown_to_plain_text(answer)]
    if sources:
        lines.extend(["", "Sources:"])
        for source in sources:
            lines.append(f"• {source['title']} · {source['source_name']}\n  {source['url']}")
    return "\n".join(lines)


def markdown_to_plain_text(value: str) -> str:
    """Flatten the model's Markdown answer; replies are sent without a parse mode."""
    text = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", r"\1 (\2)", value)
    text = re.sub(r"^\s{0,3}#{1,6}\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"^(\s*)[-*]\s+", "\\1• ", text, flags=re.MULTILINE)
    text = re.sub(r"\*\*(.+?)\*\*|__(.+?)__", lambda match: match[1] or match[2], text)
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


async def _load_discussion(session: AsyncSession) -> tuple[str, list[DiscussionMessage]]:
    setting = await session.get(AppSetting, TELEGRAM_DISCUSSION_KEY)
    value = setting.value if setting is not None and isinstance(setting.value, dict) else {}
    timeframe = value.get("timeframe")
    if timeframe not in TIMEFRAME_HOURS:
        timeframe = DEFAULT_TIMEFRAME
    if _is_idle(value.get("last_message_at")):
        return timeframe, []
    messages = [
        {"role": str(message["role"]), "content": str(message["content"])}
        for message in value.get("messages") or []
        if isinstance(message, dict) and message.get("role") and message.get("content")
    ]
    return timeframe, messages


async def _save_discussion(
    session: AsyncSession,
    timeframe: str,
    messages: list[DiscussionMessage],
) -> None:
    value: dict[str, object] = {
        "timeframe": timeframe,
        "messages": messages,
        "last_message_at": utcnow().isoformat(),
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
