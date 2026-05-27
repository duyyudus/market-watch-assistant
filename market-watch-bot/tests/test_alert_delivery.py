from __future__ import annotations

from datetime import UTC, datetime

import pytest

import bot_worker.services.pipeline as pipeline_services
from bot_worker.db.models import AlertDecisionRecord, AlertDeliveryRecord, EventCluster
from bot_worker.services.alert_delivery import (
    AlertDeliveryConfig,
    dispatch_pending_alerts,
    format_alert_message,
    send_test_alert,
)


class ExecuteRows:
    def __init__(self, rows: list[tuple[AlertDecisionRecord, EventCluster]]) -> None:
        self.rows = rows

    def all(self) -> list[tuple[AlertDecisionRecord, EventCluster]]:
        return self.rows


class DeliverySession:
    def __init__(self, rows: list[tuple[AlertDecisionRecord, EventCluster]]) -> None:
        self.rows = rows
        self.added: list[object] = []

    async def execute(self, _stmt):
        return ExecuteRows(self.rows)

    def add(self, value: object) -> None:
        self.added.append(value)


class EmptyScalarRows:
    def all(self) -> list:
        return []


class PipelineSession:
    async def scalars(self, _stmt):
        return EmptyScalarRows()


def _event(**overrides: object) -> EventCluster:
    data = {
        "id": "evt_1",
        "canonical_headline": "Oil jumps after reported shipping incident near Hormuz",
        "status": "reported",
        "affected_entities": ["Brent", "WTI"],
        "affected_tickers": ["USO"],
        "source_count": 3,
        "final_score": 86,
        "created_at": datetime(2026, 5, 27, tzinfo=UTC),
    }
    data.update(overrides)
    return EventCluster(**data)


def _alert(**overrides: object) -> AlertDecisionRecord:
    data = {
        "id": "alert_1",
        "event_cluster_id": "evt_1",
        "decision": "immediate_alert",
        "reason": "score_above_immediate_threshold",
        "score_breakdown": {},
        "created_at": datetime(2026, 5, 27, tzinfo=UTC),
    }
    data.update(overrides)
    return AlertDecisionRecord(**data)


def test_format_alert_message_uses_deterministic_fallback() -> None:
    message = format_alert_message(_alert(), _event())

    assert "[Immediate Market Alert]" in message
    assert "Oil jumps after reported shipping incident near Hormuz" in message
    assert "Status:\nreported" in message
    assert "Affected:\nBrent, WTI, USO" in message
    assert "Score:\n86" in message
    assert "Sources:\n3 report(s)" in message
    assert "score_above_immediate_threshold" in message


def test_format_alert_message_prefers_llm_alert_message() -> None:
    alert = _alert(
        score_breakdown={
            "llm": {
                "alert_message": "Oil rises on reported Gulf shipping disruption.",
                "why_it_matters": "A disruption could lift inflation expectations.",
            }
        }
    )

    message = format_alert_message(alert, _event())

    assert "Oil rises on reported Gulf shipping disruption." in message
    assert "A disruption could lift inflation expectations." in message
    assert "score_above_immediate_threshold" not in message


@pytest.mark.asyncio
async def test_dispatch_pending_alerts_sends_only_unsent_immediate_alerts() -> None:
    immediate = _alert(id="alert_send")
    digest = _alert(id="alert_digest", decision="daily_digest")
    already_sent = _alert(id="alert_sent", sent_at=datetime(2026, 5, 27, tzinfo=UTC))
    session = DeliverySession(
        [
            (immediate, _event(id="evt_send")),
            (digest, _event(id="evt_digest")),
            (already_sent, _event(id="evt_sent")),
        ]
    )
    sent_messages: list[tuple[str, str, str]] = []

    async def fake_send(config: AlertDeliveryConfig, recipient: str, message: str) -> dict:
        sent_messages.append((config.channel, recipient, message))
        return {"ok": True, "result": {"message_id": 123}}

    result = await dispatch_pending_alerts(
        session,
        AlertDeliveryConfig(
            channel="telegram",
            telegram_bot_token="token",
            telegram_chat_id="chat_1",
        ),
        send_telegram_message=fake_send,
    )

    deliveries = [value for value in session.added if isinstance(value, AlertDeliveryRecord)]
    assert result == {"pending": 0, "attempted": 1, "sent": 1, "failed": 0, "skipped": 2}
    assert len(sent_messages) == 1
    assert deliveries[0].status == "sent"
    assert deliveries[0].alert_decision_id == "alert_send"
    assert immediate.sent_at is not None
    assert immediate.channel == "telegram"


@pytest.mark.asyncio
async def test_dispatch_pending_alerts_records_failed_send_without_marking_sent() -> None:
    alert = _alert()
    session = DeliverySession([(alert, _event())])

    async def fake_send(_config: AlertDeliveryConfig, _recipient: str, _message: str) -> dict:
        raise RuntimeError("telegram unavailable")

    result = await dispatch_pending_alerts(
        session,
        AlertDeliveryConfig(
            channel="telegram",
            telegram_bot_token="token",
            telegram_chat_id="chat_1",
        ),
        send_telegram_message=fake_send,
    )

    delivery = next(value for value in session.added if isinstance(value, AlertDeliveryRecord))
    assert result == {"pending": 1, "attempted": 1, "sent": 0, "failed": 1, "skipped": 0}
    assert delivery.status == "failed"
    assert delivery.error_message == "telegram unavailable"
    assert alert.sent_at is None


@pytest.mark.asyncio
async def test_dispatch_pending_alerts_dry_run_does_not_send_or_record_delivery() -> None:
    session = DeliverySession([(_alert(), _event())])
    calls = 0

    async def fake_send(_config: AlertDeliveryConfig, _recipient: str, _message: str) -> dict:
        nonlocal calls
        calls += 1
        return {"ok": True}

    result = await dispatch_pending_alerts(
        session,
        AlertDeliveryConfig(
            channel="telegram",
            telegram_bot_token="token",
            telegram_chat_id="chat_1",
        ),
        dry_run=True,
        send_telegram_message=fake_send,
    )

    assert result == {"pending": 1, "attempted": 0, "sent": 0, "failed": 0, "skipped": 0}
    assert calls == 0
    assert session.added == []


@pytest.mark.asyncio
async def test_send_test_alert_records_failed_delivery_without_raising() -> None:
    session = DeliverySession([])

    async def fake_send(_config: AlertDeliveryConfig, _recipient: str, _message: str) -> dict:
        raise RuntimeError("telegram unavailable")

    result = await send_test_alert(
        session,
        AlertDeliveryConfig(
            channel="telegram",
            telegram_bot_token="token",
            telegram_chat_id="chat_1",
        ),
        "hello",
        send_telegram_message=fake_send,
    )

    delivery = next(value for value in session.added if isinstance(value, AlertDeliveryRecord))
    assert result["status"] == "failed"
    assert result["error"] == "telegram unavailable"
    assert delivery.status == "failed"
    assert delivery.alert_decision_id is None


@pytest.mark.asyncio
async def test_run_pipeline_reports_alert_delivery_counts(monkeypatch) -> None:
    order: list[str] = []

    async def zero(*_args, **_kwargs) -> int:
        return 0

    async def extract_zero(*_args, **_kwargs) -> int:
        order.append("extract_entities")
        return 0

    async def embed_zero(*_args, **_kwargs) -> int:
        order.append("embed_news")
        return 0

    async def cluster_zero(*_args, **kwargs):
        order.append("cluster")
        assert kwargs["llm_config"].api_key == "key"
        return pipeline_services.ClusterBuildStats(
            created_clusters=0,
            attached_existing=1,
            llm_cluster_decisions=1,
            llm_cluster_attaches=1,
        )

    async def one_alert(_session) -> int:
        return 1

    async def fake_dispatch(_session, _config):
        return {"pending": 1, "attempted": 3, "sent": 2, "failed": 1, "skipped": 0}

    monkeypatch.setattr(pipeline_services, "normalize_pending_raw_items", zero)
    monkeypatch.setattr(pipeline_services, "mark_exact_duplicates", zero)
    monkeypatch.setattr(pipeline_services, "extract_entities_with_llm", extract_zero)
    monkeypatch.setattr(pipeline_services, "embed_pending_news_items", embed_zero)
    monkeypatch.setattr(pipeline_services, "build_event_clusters", cluster_zero)
    monkeypatch.setattr(pipeline_services, "record_alert_decisions", one_alert)
    monkeypatch.setattr(pipeline_services, "dispatch_pending_alerts", fake_dispatch)

    result = await pipeline_services.run_pipeline(
        PipelineSession(),
        alert_delivery_config=AlertDeliveryConfig(
            channel="telegram",
            telegram_bot_token="token",
            telegram_chat_id="chat_1",
        ),
        llm_config=pipeline_services.LLMConfig(enabled=True, api_key="key"),
        embedding_config=pipeline_services.EmbeddingConfig(provider="local"),
    )

    assert order == ["extract_entities", "embed_news", "cluster"]
    assert result["entities_extracted"] == 0
    assert result["clusters"] == 0
    assert result["cluster_attached_existing"] == 1
    assert result["llm_cluster_decisions"] == 1
    assert result["llm_cluster_attaches"] == 1
    assert result["alerts"] == 1
    assert result["delivered_alerts"] == 2
    assert result["failed_alert_deliveries"] == 1
