from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from bot_worker.db.models import AppSetting
from bot_worker.services.alert_delivery import AlertDeliveryConfig
from bot_worker.services.telegram_commands import process_telegram_updates
from bot_worker.services.telegram_discussion import (
    TELEGRAM_DISCUSSION_KEY,
    TELEGRAM_MESSAGE_CHARACTER_LIMIT,
    format_discussion_reply,
    split_telegram_message,
)
from common.db.models import utcnow

CONFIG = AlertDeliveryConfig(
    channel="telegram",
    telegram_bot_token="token",
    telegram_chat_id="chat_1",
)


class SettingsSession:
    def __init__(self) -> None:
        self.settings: dict[str, AppSetting] = {}

    async def get(self, model, key):
        assert model is AppSetting
        return self.settings.get(key)

    def add(self, value: object) -> None:
        assert isinstance(value, AppSetting)
        self.settings[value.key] = value

    def discussion(self) -> dict:
        return self.settings[TELEGRAM_DISCUSSION_KEY].value


class Chat:
    """Drives process_telegram_updates one message at a time with a fake answerer."""

    def __init__(self, *, chat_type: str = "private") -> None:
        self.session = SettingsSession()
        self.chat_type = chat_type
        self.sent: list[tuple[str, int | None]] = []
        self.requests: list[tuple[str, list[dict[str, str]], object]] = []
        self.result: dict | Exception = {"status": "answered", "answer": "Answer", "sources": []}
        self.update_id = 0

    async def answer(self, _session, timeframe, messages, previous_window):
        self.requests.append((timeframe, messages, previous_window))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result

    async def send_reply(self, _config, _chat_id, message, reply_to_message_id):
        self.sent.append((message, reply_to_message_id))
        return {"ok": True}

    async def say(self, text: str) -> dict[str, int]:
        self.update_id += 1
        return await process_telegram_updates(
            self.session,
            CONFIG,
            [
                {
                    "update_id": self.update_id,
                    "message": {
                        "message_id": 100 + self.update_id,
                        "chat": {"id": "chat_1", "type": self.chat_type},
                        "text": text,
                    },
                }
            ],
            answer_question=self.answer,
            send_reply=self.send_reply,
        )


WEEK_START = datetime(2026, 5, 23, 12, 0, tzinfo=UTC)


def _auto_result(source: str, *, label: str = "last 7 days", end=None) -> dict:
    return {
        "status": "answered",
        "answer": "Oil supply tightened.",
        "sources": [],
        "context_window": {"start": WEEK_START, "end": end, "label": label, "source": source},
    }


@pytest.mark.asyncio
async def test_plain_message_is_answered_on_auto_and_continues_the_conversation() -> None:
    chat = Chat()
    chat.result = {
        "status": "answered",
        "answer": "## Rates\n- **Yields** fell, see [the wire](https://example.test/a).",
        "sources": [
            {"title": "Rates fall", "source_name": "Test Wire", "url": "https://example.test/a"}
        ],
    }

    counts = await chat.say("What did rates do?")
    await chat.say("And equities?")

    assert counts == {"updates": 1, "processed": 1, "ignored": 0, "replied": 1, "failed": 0}
    assert chat.sent[0] == (
        "Rates\n• Yields fell, see the wire (https://example.test/a).\n\n"
        "Sources:\n• Rates fall · Test Wire\n  https://example.test/a",
        101,
    )
    # Auto is the default, like the dashboard chat box.
    assert chat.requests[0] == ("auto", [{"role": "user", "content": "What did rates do?"}], None)
    assert [message["content"] for message in chat.requests[1][1]] == [
        "What did rates do?",
        chat.result["answer"],
        "And equities?",
    ]
    assert len(chat.session.discussion()["messages"]) == 4


@pytest.mark.asyncio
async def test_group_messages_are_questions_and_ask_is_no_longer_a_command() -> None:
    chat = Chat(chat_type="supergroup")

    answered = await chat.say("what happened today?")
    ignored = await chat.say("/ask what happened today?")

    assert answered["replied"] == 1
    assert ignored["ignored"] == 1
    assert [messages[-1]["content"] for _timeframe, messages, _window in chat.requests] == [
        "what happened today?"
    ]


@pytest.mark.asyncio
async def test_auto_window_is_captioned_and_carried_into_follow_ups() -> None:
    chat = Chat()
    chat.result = _auto_result("inferred")

    await chat.say("Oil supply last week")
    chat.result = _auto_result("carried")
    await chat.say("And gold?")

    assert chat.sent[0][0] == (
        "Oil supply tightened.\n\nSearched last 7 days · from your question"
    )
    assert chat.sent[1][0] == (
        "Oil supply tightened.\n\nSearched last 7 days · same as previous answer"
    )
    assert chat.requests[0][2] is None
    assert chat.requests[1][2] == (WEEK_START, None)
    assert chat.session.discussion()["previous_window"] == {
        "start": WEEK_START.isoformat(),
        "end": None,
    }

    await chat.say("/new")
    await chat.say("Fresh topic")

    assert chat.requests[2][2] is None


@pytest.mark.asyncio
async def test_fallback_and_fixed_windows_are_not_carried() -> None:
    chat = Chat()
    chat.result = {
        **_auto_result("fallback", label="last 24 hours"),
        "answer": (
            "Rates eased.\n\n_No time period found in your question, so I searched "
            "articles from the last 24 hours._"
        ),
    }

    await chat.say("What moved rates?")
    chat.result = _auto_result("selected", label="last 24 hours")
    await chat.say("And equities?")

    # The note's Markdown italics are flattened for plain-text Telegram replies.
    assert chat.sent[0][0] == (
        "Rates eased.\n\nNo time period found in your question, so I searched articles "
        "from the last 24 hours.\n\nSearched last 24 hours"
    )
    assert chat.sent[1][0] == "Oil supply tightened."
    assert chat.requests[1][2] is None
    assert "previous_window" not in chat.session.discussion()


@pytest.mark.asyncio
async def test_new_and_timeframe_commands_reset_the_conversation() -> None:
    chat = Chat()

    await chat.say("First question")
    await chat.say("/timeframe 7d")
    await chat.say("Second question")
    await chat.say("/new")
    await chat.say("Third question")
    await chat.say("/timeframe 2w")
    await chat.say("/timeframe")

    assert chat.requests[1] == ("7d", [{"role": "user", "content": "Second question"}], None)
    assert chat.requests[2] == ("7d", [{"role": "user", "content": "Third question"}], None)
    assert chat.sent[1][0] == "Started a new chat. Article context: last 7 days."
    assert chat.sent[-2][0] == (
        "Unknown timeframe. Choose one of: auto, 24h, 3d, 7d, 30d, max."
    )
    assert chat.sent[-1][0] == (
        "Article context: last 7 days. "
        "Change it with /timeframe <auto, 24h, 3d, 7d, 30d, max>."
    )
    assert chat.session.discussion()["timeframe"] == "7d"


@pytest.mark.asyncio
async def test_timeframe_accepts_auto_and_max() -> None:
    chat = Chat()

    await chat.say("/timeframe max")
    await chat.say("Long story")
    await chat.say("/timeframe auto")

    assert chat.requests[0][0] == "max"
    assert chat.sent[0][0] == (
        "Started a new chat. Article context: Max (the longest configured window)."
    )
    assert chat.sent[-1][0] == (
        "Started a new chat. Article context: "
        "Auto (from your question; last 24 hours if it names no period)."
    )


@pytest.mark.asyncio
async def test_idle_conversation_starts_over() -> None:
    chat = Chat()

    await chat.say("First question")
    chat.session.settings[TELEGRAM_DISCUSSION_KEY].value = {
        **chat.session.discussion(),
        "last_message_at": (utcnow() - timedelta(hours=2)).isoformat(),
    }
    await chat.say("Second question")

    assert chat.requests[1][1] == [{"role": "user", "content": "Second question"}]


@pytest.mark.asyncio
async def test_failed_answer_is_reported_and_keeps_history_unchanged() -> None:
    chat = Chat()
    chat.result = ValueError("OPENROUTER_API_KEY is required for discussion chat")

    counts = await chat.say("What happened?")

    assert counts["replied"] == 1
    assert chat.sent == [("OPENROUTER_API_KEY is required for discussion chat", 101)]
    assert TELEGRAM_DISCUSSION_KEY not in chat.session.settings


@pytest.mark.asyncio
async def test_long_answer_is_split_and_only_the_first_part_is_a_reply() -> None:
    chat = Chat()
    chat.result = {"status": "answered", "answer": "\n".join(["line " * 20] * 60), "sources": []}

    counts = await chat.say("Long one")

    assert counts["replied"] == 1
    assert len(chat.sent) == 2
    assert [reply_to for _message, reply_to in chat.sent] == [101, None]
    assert all(len(message) <= TELEGRAM_MESSAGE_CHARACTER_LIMIT for message, _ in chat.sent)


def test_split_telegram_message_hard_cuts_text_without_newlines() -> None:
    chunks = split_telegram_message("x" * (TELEGRAM_MESSAGE_CHARACTER_LIMIT + 5))

    assert [len(chunk) for chunk in chunks] == [TELEGRAM_MESSAGE_CHARACTER_LIMIT, 5]


def test_format_discussion_reply_without_sources_is_just_the_answer() -> None:
    assert format_discussion_reply("Not enough evidence.", []) == "Not enough evidence."


def test_format_discussion_reply_lists_sources_with_outlet_and_local_time() -> None:
    reply = format_discussion_reply(
        "Rates eased.",
        [
            {
                "title": "Fed signals a slower rate path",
                "source_name": "Reuters",
                "url": "https://example.test/fed",
                "published_at": datetime(2026, 5, 29, 13, 5, tzinfo=UTC),
            },
            {
                "title": "Undated wire",
                "source_name": "Test Wire",
                "url": "https://example.test/wire",
                "published_at": None,
            },
        ],
        timezone=ZoneInfo("Asia/Ho_Chi_Minh"),
    )

    assert reply == (
        "Rates eased.\n\n"
        "Sources:\n"
        "• Fed signals a slower rate path · Reuters · May 29, 20:05\n"
        "  https://example.test/fed\n"
        "• Undated wire · Test Wire\n"
        "  https://example.test/wire"
    )
