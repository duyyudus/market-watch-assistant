from __future__ import annotations

from datetime import UTC, datetime

import pytest

import bot_worker.services.alerts as alert_services
from bot_worker.db.models import (
    AgentInvestigation,
    AlertDecisionRecord,
    EventCluster,
    LLMAnalysisRun,
)
from bot_worker.llm import PROMPT_VERSION
from bot_worker.scoring import ScoreInput, score_event


class ScalarRows:
    def __init__(self, rows: list[object]) -> None:
        self.rows = rows

    def all(self) -> list[object]:
        return self.rows


class ExecuteRows:
    def __init__(self, rows: list[object]) -> None:
        self.rows = rows

    def all(self) -> list[object]:
        return self.rows

    def scalar_one_or_none(self) -> object | None:
        return None


class AlertDecisionSession:
    def __init__(
        self,
        event: EventCluster,
        *,
        latest_alert: AlertDecisionRecord | None = None,
        llm_run: LLMAnalysisRun | None = None,
        investigation: AgentInvestigation | None = None,
    ) -> None:
        self.event = event
        self.latest_alert = latest_alert
        self.llm_run = llm_run
        self.investigation = investigation
        self.added: list[object] = []

    async def scalars(self, stmt):
        if "event_clusters" in str(stmt):
            return ScalarRows([self.event])
        return ScalarRows([])

    async def scalar(self, _stmt):
        return None

    async def execute(self, stmt):
        text = str(stmt)
        if "alert_decisions" in text and self.latest_alert is not None:
            return ExecuteRows([self.latest_alert])
        if "llm_analysis_runs" in text and self.llm_run is not None:
            return ExecuteRows([self.llm_run])
        if "agent_investigations" in text and self.investigation is not None:
            return ExecuteRows([self.investigation])
        return ExecuteRows([])

    def add(self, value: object) -> None:
        self.added.append(value)


class MultiAlertDecisionSession:
    def __init__(self, events: list[EventCluster]) -> None:
        self.events = events
        self.added: list[object] = []

    async def scalars(self, stmt):
        text = str(stmt)
        if (
            "event_clusters.status NOT IN" in text
            and "event_clusters.compacted_at IS NULL" in text
        ):
            rows = [
                event
                for event in self.events
                if event.status not in {"stale", "merged"} and event.compacted_at is None
            ]
            return ScalarRows(rows)
        return ScalarRows(self.events)

    async def scalar(self, _stmt):
        return None

    async def execute(self, _stmt):
        return ExecuteRows([])

    def add(self, value: object) -> None:
        self.added.append(value)


def event(**overrides: object) -> EventCluster:
    values = {
        "id": "evt_1",
        "canonical_headline": "Oil jumps after reported Gulf shipping disruption",
        "status": "reported",
        "regions": ["global"],
        "asset_classes": ["commodity"],
        "affected_entities": ["Brent"],
        "affected_tickers": ["USO"],
        "source_count": 1,
        "high_quality_source_count": 0,
        "top_source_score": 92,
        "final_score": 82,
        "created_at": datetime(2026, 5, 28, tzinfo=UTC),
        "last_updated_at": datetime(2026, 5, 28, 1, tzinfo=UTC),
    }
    values.update(overrides)
    return EventCluster(**values)


def alert(**overrides: object) -> AlertDecisionRecord:
    values = {
        "id": "alert_1",
        "event_cluster_id": "evt_1",
        "decision": "daily_digest",
        "reason": "score_above_digest_threshold",
        "score_breakdown": {"final_score": 40},
        "created_at": datetime(2026, 5, 28, tzinfo=UTC),
    }
    values.update(overrides)
    return AlertDecisionRecord(**values)


@pytest.mark.asyncio
async def test_record_alert_decisions_appends_when_existing_decision_escalates(
    monkeypatch,
) -> None:
    session = AlertDecisionSession(
        event(last_updated_at=datetime(2026, 5, 28, 2, tzinfo=UTC)),
        latest_alert=alert(decision="daily_digest"),
    )

    async def market_score(_session, _cluster):
        return 0

    monkeypatch.setattr(
        alert_services, "market_move_score_for_cluster", market_score, raising=False
    )

    count = await alert_services.record_alert_decisions(session)

    assert count == 1
    new_alert = next(item for item in session.added if isinstance(item, AlertDecisionRecord))
    assert new_alert.decision == "watchlist_batch"


@pytest.mark.asyncio
async def test_record_alert_decisions_updates_cluster_without_duplicate_same_tier(
    monkeypatch,
) -> None:
    cluster = event(
        top_source_score=80,
        source_count=1,
        high_quality_source_count=0,
        last_updated_at=datetime(2026, 5, 28, 2, tzinfo=UTC),
    )
    session = AlertDecisionSession(cluster, latest_alert=alert(decision="watchlist_batch"))

    async def market_score(_session, _cluster):
        return 0

    monkeypatch.setattr(
        alert_services, "market_move_score_for_cluster", market_score, raising=False
    )

    count = await alert_services.record_alert_decisions(session)

    assert count == 0
    assert cluster.final_score >= 55
    assert not any(isinstance(item, AlertDecisionRecord) for item in session.added)


@pytest.mark.asyncio
async def test_record_alert_decisions_does_not_recreate_existing_immediate_alert(
    monkeypatch,
) -> None:
    cluster = event(last_updated_at=datetime(2026, 5, 28, tzinfo=UTC))
    session = AlertDecisionSession(
        cluster,
        latest_alert=alert(
            decision="immediate_alert",
            created_at=datetime(2026, 5, 28, 1, tzinfo=UTC),
        ),
    )

    async def market_score(_session, _cluster):
        return 0

    monkeypatch.setattr(
        alert_services, "market_move_score_for_cluster", market_score, raising=False
    )

    count = await alert_services.record_alert_decisions(session)

    assert count == 0
    assert not any(isinstance(item, AlertDecisionRecord) for item in session.added)


@pytest.mark.asyncio
async def test_record_alert_decisions_does_not_append_first_archive_only_decision() -> None:
    cluster = event(
        top_source_score=10,
        source_count=1,
        affected_entities=[],
        affected_tickers=[],
    )
    session = AlertDecisionSession(cluster)

    count = await alert_services.record_alert_decisions(session)

    assert count == 0
    assert cluster.final_score < 30
    assert not any(isinstance(item, AlertDecisionRecord) for item in session.added)


@pytest.mark.asyncio
async def test_record_alert_decisions_applies_combined_model_modifier_cap(
    monkeypatch,
) -> None:
    cluster = event(top_source_score=70, source_count=1)
    session = AlertDecisionSession(
        cluster,
        llm_run=LLMAnalysisRun(
            id="llm_1",
            target_type="event_cluster",
            target_id=cluster.id,
            provider="openrouter",
            model="model",
            prompt_version=PROMPT_VERSION,
            prompt_hash="hash",
            input_snapshot={},
            result={
                "summary": "Model summary",
                "score_modifier": 8,
                "confidence": 85,
            },
            status="succeeded",
        ),
        investigation=AgentInvestigation(
            id="inv_1",
            target_type="event_cluster",
            target_id=cluster.id,
            trigger_reason="manual",
            status="succeeded",
            input_snapshot={},
            evidence=[],
            result={
                "summary": "Investigation summary",
                "confidence": 80,
                "suggested_score_modifier": 8,
            },
        ),
    )
    deterministic = score_event(
        ScoreInput(
            top_source_score=cluster.top_source_score,
            source_count=cluster.source_count,
            watchlist_tier="A",
            is_duplicate=False,
            is_stale=False,
            unique_high_quality_source_count=0,
            status=cluster.status,
            market_move_score=None,
        )
    )

    async def market_score(_session, _cluster):
        return 0

    monkeypatch.setattr(
        alert_services, "market_move_score_for_cluster", market_score, raising=False
    )

    count = await alert_services.record_alert_decisions(session)

    assert count == 1
    new_alert = next(item for item in session.added if isinstance(item, AlertDecisionRecord))
    assert new_alert.score_breakdown["deterministic_final_score"] == deterministic.final_score
    assert new_alert.score_breakdown["final_score"] == deterministic.final_score + 10


@pytest.mark.asyncio
async def test_record_alert_decisions_filters_inactive_clusters(monkeypatch) -> None:
    session = MultiAlertDecisionSession(
        [
            event(id="evt_active"),
            event(id="evt_stale", status="stale"),
            event(id="evt_merged", status="merged"),
            event(id="evt_compacted", compacted_at=datetime(2026, 5, 29, tzinfo=UTC)),
        ]
    )
    count = await alert_services.record_alert_decisions(session)

    assert count == 1
    alert = next(item for item in session.added if isinstance(item, AlertDecisionRecord))
    assert alert.event_cluster_id == "evt_active"


@pytest.mark.asyncio
async def test_record_alert_decisions_uses_batched_enrichment_lookups(monkeypatch) -> None:
    session = AlertDecisionSession(event())

    async def fail_market_score(_session, _cluster):
        raise AssertionError("per-cluster market lookup should not run")

    async def fail_llm_lookup(_session, _cluster_id):
        raise AssertionError("per-cluster LLM lookup should not run")

    async def fail_investigation_lookup(_session, **_kwargs):
        raise AssertionError("per-cluster investigation lookup should not run")

    monkeypatch.setattr(
        alert_services, "market_move_score_for_cluster", fail_market_score, raising=False
    )
    monkeypatch.setattr(
        alert_services, "latest_successful_llm_analysis", fail_llm_lookup, raising=False
    )
    monkeypatch.setattr(
        alert_services,
        "latest_successful_investigation",
        fail_investigation_lookup,
        raising=False,
    )

    count = await alert_services.record_alert_decisions(session)

    assert count == 1
