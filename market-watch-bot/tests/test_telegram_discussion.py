from __future__ import annotations

from datetime import timedelta

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
        self.requests: list[tuple[str, list[dict[str, str]]]] = []
        self.result: dict | Exception = {"status": "answered", "answer": "Answer", "sources": []}
        self.update_id = 0

    async def answer(self, _session, timeframe, messages):
        self.requests.append((timeframe, messages))
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


@pytest.mark.asyncio
async def test_plain_private_message_is_answered_and_continues_the_conversation() -> None:
    chat = Chat()
    chat.result = {
        "status": "answered",
        "answer": "## Rates\n- **Yields** fell, see [the wire](https://example.test/a).",
        "sources": [
            {"title": "Rates fall", "source_name": "Test Wire", "url": "https://example.test/a"}
        ],
    }

    counts = await chat.say("What did rates do?")
    await chat.say("/ask@market_bot And equities?")

    assert counts == {"updates": 1, "processed": 1, "ignored": 0, "replied": 1, "failed": 0}
    assert chat.sent[0] == (
        "Rates\n• Yields fell, see the wire (https://example.test/a).\n\n"
        "Sources:\n• Rates fall · Test Wire\n  https://example.test/a",
        101,
    )
    assert chat.requests[0] == ("24h", [{"role": "user", "content": "What did rates do?"}])
    assert [message["content"] for message in chat.requests[1][1]] == [
        "What did rates do?",
        chat.result["answer"],
        "And equities?",
    ]
    assert len(chat.session.discussion()["messages"]) == 4


@pytest.mark.asyncio
async def test_group_chat_requires_ask_command() -> None:
    chat = Chat(chat_type="supergroup")

    ignored = await chat.say("what happened today?")
    usage = await chat.say("/ask")
    await chat.say("/ask what happened today?")

    assert ignored["ignored"] == 1
    assert usage["replied"] == 1
    assert "/ask" in chat.sent[0][0]
    assert [messages[-1]["content"] for _timeframe, messages in chat.requests] == [
        "what happened today?"
    ]


@pytest.mark.asyncio
async def test_new_and_timeframe_commands_reset_the_conversation() -> None:
    chat = Chat()

    await chat.say("First question")
    await chat.say("/timeframe 7d")
    await chat.say("Second question")
    await chat.say("/new")
    await chat.say("Third question")
    await chat.say("/timeframe 2w")

    assert chat.requests[1] == ("7d", [{"role": "user", "content": "Second question"}])
    assert chat.requests[2] == ("7d", [{"role": "user", "content": "Third question"}])
    assert chat.sent[1][0] == "Started a new chat. Article context: last 7d."
    assert chat.sent[-1][0] == "Unknown timeframe. Choose one of: 24h, 3d, 7d, 30d."
    assert chat.session.discussion()["timeframe"] == "7d"


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
