from __future__ import annotations

from datetime import UTC, datetime

import pytest

from bot_worker.db.models import (
    AlertDecisionRecord,
    AlertDeliveryRecord,
    AppSetting,
    EventCluster,
    NormalizedNewsItem,
)
from bot_worker.services.alert_delivery import AlertDeliveryConfig
from bot_worker.services.telegram_commands import (
    TELEGRAM_COMMAND_OFFSET_KEY,
    find_alert_detail_for_telegram_message,
    format_alert_detail_message,
    process_telegram_updates,
    register_telegram_bot_commands,
)


class ScalarResult:
    def __init__(self, value: object | None) -> None:
        self.value = value

    def first(self) -> object | None:
        return self.value


class ExecuteRows:
    def __init__(self, rows: list[tuple]) -> None:
        self.rows = rows

    def first(self):
        return self.rows[0] if self.rows else None

    def all(self) -> list[tuple]:
        return self.rows


class DetailSession:
    def __init__(self) -> None:
        self.event = EventCluster(
            id="evt_1",
            canonical_headline="Oil jumps after shipping disruption",
            status="reported",
            source_count=3,
            final_score=86,
        )
        self.alert = AlertDecisionRecord(
            id="alert_1",
            event_cluster_id="evt_1",
            decision="immediate_alert",
            reason="score_above_immediate_threshold",
            score_breakdown={},
            created_at=datetime(2026, 5, 27, tzinfo=UTC),
        )
        self.delivery = AlertDeliveryRecord(
            id="delivery_1",
            alert_decision_id="alert_1",
            channel="telegram",
            recipient="chat_1",
            status="sent",
            message_text="alert",
            provider_response={"ok": True, "result": {"message_id": 123}},
        )
        self.articles = [
            NormalizedNewsItem(
                id=f"news_{index}",
                source_id="src_1",
                title=f"Article {index}",
                url=f"https://example.test/{index}",
                source_name="Example",
                source_type="rss",
                source_score=80,
                region="global",
                asset_classes=["commodity"],
                title_hash=f"title_{index}",
                normalized_text_hash=f"text_{index}",
                processing_status="clustered",
            )
            for index in range(1, 4)
        ]

    async def scalars(self, stmt):
        text = str(stmt)
        if "alert_deliveries" in text:
            return ScalarResult(self.delivery)
        raise AssertionError(f"unexpected scalar query: {text}")

    async def execute(self, stmt):
        text = str(stmt)
        if "alert_decisions" in text and "event_clusters" in text:
            return ExecuteRows([(self.alert, self.event)])
        if "normalized_news_items" in text:
            return ExecuteRows([(article,) for article in self.articles])
        raise AssertionError(f"unexpected execute query: {text}")


class OffsetSession(DetailSession):
    def __init__(self) -> None:
        super().__init__()
        self.setting: AppSetting | None = None
        self.added: list[object] = []

    async def get(self, model, key):
        assert model is AppSetting
        assert key == TELEGRAM_COMMAND_OFFSET_KEY
        return self.setting

    def add(self, value: object) -> None:
        self.added.append(value)
        if isinstance(value, AppSetting):
            self.setting = value


def test_format_alert_detail_message_caps_articles() -> None:
    event = EventCluster(
        id="evt_1",
        canonical_headline="Oil jumps after shipping disruption",
        status="reported",
        source_count=3,
        final_score=86,
    )
    alert = AlertDecisionRecord(
        id="alert_1",
        event_cluster_id="evt_1",
        decision="immediate_alert",
        reason="score_above_immediate_threshold",
        score_breakdown={},
    )
    articles = [
        NormalizedNewsItem(
            id=f"news_{index}",
            source_id="src_1",
            title=f"Article {index}",
            url=f"https://example.test/{index}",
            source_name="Example",
            source_type="rss",
            source_score=80,
            region="global",
            asset_classes=[],
            title_hash=f"title_{index}",
            normalized_text_hash=f"text_{index}",
        )
        for index in range(1, 4)
    ]

    message = format_alert_detail_message(alert, event, articles, article_limit=2)

    assert "Oil jumps after shipping disruption" in message
    assert "Alert: alert_1" in message
    assert "- Article 1\n  https://example.test/1" in message
    assert "- Article 2\n  https://example.test/2" in message
    assert "Article 3" not in message


@pytest.mark.asyncio
async def test_find_alert_detail_for_telegram_message_returns_related_articles() -> None:
    detail = await find_alert_detail_for_telegram_message(
        DetailSession(),
        telegram_message_id=123,
        chat_id="chat_1",
        article_limit=2,
    )

    assert detail is not None
    assert detail.alert.id == "alert_1"
    assert detail.event.id == "evt_1"
    assert [article.id for article in detail.articles] == ["news_1", "news_2"]


@pytest.mark.asyncio
async def test_find_alert_detail_for_telegram_message_requires_matching_chat() -> None:
    detail = await find_alert_detail_for_telegram_message(
        DetailSession(),
        telegram_message_id=123,
        chat_id="other_chat",
        article_limit=2,
    )

    assert detail is None


@pytest.mark.asyncio
async def test_register_telegram_bot_commands_sets_detail_command(monkeypatch) -> None:
    requests: list[tuple[str, dict[str, object]]] = []

    class Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {"ok": True, "result": True}

    class Client:
        def __init__(self, *, timeout: int) -> None:
            assert timeout == 20

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args) -> None:
            return None

        async def post(self, url: str, json: dict[str, object]):
            requests.append((url, json))
            return Response()

    monkeypatch.setattr("bot_worker.services.telegram_commands.httpx.AsyncClient", Client)

    result = await register_telegram_bot_commands(
        AlertDeliveryConfig(
            channel="telegram",
            telegram_bot_token="secret-token",
            telegram_chat_id="chat_1",
        )
    )

    assert result == {"ok": True, "result": True}
    assert requests == [
        (
            "https://api.telegram.org/botsecret-token/setMyCommands",
            {
                "commands": [
                    {
                        "command": "detail",
                        "description": "Show article titles and URLs for a replied alert",
                    }
                ],
                "scope": {"type": "chat", "chat_id": "chat_1"},
            },
        )
    ]


@pytest.mark.asyncio
async def test_process_detail_requires_reply_to_alert_message() -> None:
    session = OffsetSession()
    sent: list[tuple[str, str, int | None]] = []

    async def fake_send_reply(
        _config: AlertDeliveryConfig,
        chat_id: str,
        message: str,
        reply_to_message_id: int | None,
    ) -> dict:
        sent.append((chat_id, message, reply_to_message_id))
        return {"ok": True}

    result = await process_telegram_updates(
        session,
        AlertDeliveryConfig(
            channel="telegram",
            telegram_bot_token="token",
            telegram_chat_id="chat_1",
        ),
        [
            {
                "update_id": 10,
                "message": {
                    "message_id": 456,
                    "chat": {"id": "chat_1"},
                    "text": "/detail",
                },
            }
        ],
        send_reply=fake_send_reply,
    )

    assert result == {"updates": 1, "processed": 1, "ignored": 0, "replied": 1, "failed": 0}
    assert sent == [("chat_1", "Reply to an alert message with /detail.", 456)]


@pytest.mark.asyncio
async def test_process_detail_reports_unknown_replied_message() -> None:
    session = OffsetSession()
    session.delivery.provider_response = {"ok": True, "result": {"message_id": 999}}
    sent: list[str] = []

    async def fake_send_reply(
        _config: AlertDeliveryConfig,
        _chat_id: str,
        message: str,
        _reply_to_message_id: int | None,
    ) -> dict:
        sent.append(message)
        return {"ok": True}

    await process_telegram_updates(
        session,
        AlertDeliveryConfig(
            channel="telegram",
            telegram_bot_token="token",
            telegram_chat_id="chat_1",
        ),
        [
            {
                "update_id": 10,
                "message": {
                    "message_id": 456,
                    "chat": {"id": "chat_1"},
                    "text": "/detail",
                    "reply_to_message": {"message_id": 123},
                },
            }
        ],
        send_reply=fake_send_reply,
    )

    assert sent == ["I could not find an alert for that message."]


@pytest.mark.asyncio
async def test_process_updates_ignores_other_chats_and_stores_next_offset() -> None:
    session = OffsetSession()
    sent: list[str] = []

    async def fake_send_reply(
        _config: AlertDeliveryConfig,
        _chat_id: str,
        message: str,
        _reply_to_message_id: int | None,
    ) -> dict:
        sent.append(message)
        return {"ok": True}

    result = await process_telegram_updates(
        session,
        AlertDeliveryConfig(
            channel="telegram",
            telegram_bot_token="token",
            telegram_chat_id="chat_1",
        ),
        [
            {
                "update_id": 10,
                "message": {
                    "message_id": 456,
                    "chat": {"id": "other_chat"},
                    "text": "/detail",
                    "reply_to_message": {"message_id": 123},
                },
            },
            {
                "update_id": 11,
                "message": {
                    "message_id": 457,
                    "chat": {"id": "chat_1"},
                    "text": "hello",
                },
            },
        ],
        send_reply=fake_send_reply,
    )

    assert result == {"updates": 2, "processed": 0, "ignored": 2, "replied": 0, "failed": 0}
    assert sent == []
    assert session.setting is not None
    assert session.setting.value == {"offset": 12}


@pytest.mark.asyncio
async def test_process_updates_advances_offset_when_one_reply_fails() -> None:
    session = OffsetSession()
    sent: list[str] = []

    async def flaky_send_reply(
        _config: AlertDeliveryConfig,
        _chat_id: str,
        message: str,
        _reply_to_message_id: int | None,
    ) -> dict:
        if "Article 1" in message:
            raise RuntimeError("telegram send failed")
        sent.append(message)
        return {"ok": True}

    result = await process_telegram_updates(
        session,
        AlertDeliveryConfig(
            channel="telegram",
            telegram_bot_token="token",
            telegram_chat_id="chat_1",
        ),
        [
            {
                "update_id": 10,
                "message": {
                    "message_id": 456,
                    "chat": {"id": "chat_1"},
                    "text": "/detail",
                    "reply_to_message": {"message_id": 123},
                },
            },
            {
                "update_id": 11,
                "message": {
                    "message_id": 457,
                    "chat": {"id": "chat_1"},
                    "text": "/detail",
                },
            },
        ],
        send_reply=flaky_send_reply,
    )

    assert result == {"updates": 2, "processed": 2, "ignored": 0, "replied": 1, "failed": 1}
    assert sent == ["Reply to an alert message with /detail."]
    assert session.setting is not None
    assert session.setting.value == {"offset": 12}
