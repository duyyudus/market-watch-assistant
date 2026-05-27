import asyncio
from datetime import UTC, datetime

import pytest

import bot_worker.services as services
from bot_worker.db.models import (
    AlertDecisionRecord,
    EventCluster,
    LLMAnalysisRun,
    NormalizedNewsItem,
)
from bot_worker.llm import LLMAnalysis, LLMClassification, LLMConfig, LLMEventScore, LLMEventSummary


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


class FakeLLMSession:
    def __init__(
        self,
        clusters: list[EventCluster],
        existing_runs: list[LLMAnalysisRun] | None = None,
    ) -> None:
        self.clusters = clusters
        self.existing_runs = existing_runs or []
        self.added: list[object] = []
        self.scalar_calls = 0

    async def scalars(self, _stmt):
        self.scalar_calls += 1
        return ScalarRows(self.clusters)

    async def scalar(self, _stmt):
        if self.existing_runs:
            return self.existing_runs.pop(0)
        return None

    def add(self, value: object) -> None:
        self.added.append(value)

    async def flush(self) -> None:
        return None


class FakeAlertSession:
    def __init__(self, event: EventCluster, run: LLMAnalysisRun | None) -> None:
        self.event = event
        self.run = run
        self.added: list[object] = []

    async def scalars(self, _stmt):
        return ScalarRows([self.event])

    async def scalar(self, _stmt):
        return self.run

    def add(self, value: object) -> None:
        self.added.append(value)


class FakeTargetSession:
    def __init__(self, target: object) -> None:
        self.target = target
        self.added: list[object] = []

    async def get(self, _model, _key):
        return self.target

    async def scalar(self, _stmt):
        return None

    def add(self, value: object) -> None:
        self.added.append(value)

    async def flush(self) -> None:
        return None


@pytest.mark.asyncio
async def test_enrich_event_clusters_skips_when_api_key_missing() -> None:
    event = EventCluster(
        id="evt_1",
        canonical_headline="Fed surprise statement",
        final_score=85,
        source_count=1,
        top_source_score=95,
        created_at=datetime(2026, 5, 27, tzinfo=UTC),
    )
    session = FakeLLMSession([event])

    count = await services.enrich_event_clusters_with_llm(
        session,
        config=LLMConfig(enabled=True, api_key=None),
    )

    assert count == 0
    assert session.added == []


@pytest.mark.asyncio
async def test_enrich_event_clusters_records_successful_structured_result(monkeypatch) -> None:
    event = EventCluster(
        id="evt_1",
        canonical_headline="Oil jumps after Hormuz disruption",
        final_score=86,
        source_count=1,
        top_source_score=92,
        created_at=datetime(2026, 5, 27, tzinfo=UTC),
    )
    session = FakeLLMSession([event])

    class FakeProvider:
        async def analyze_event(self, _prompt: str) -> tuple[LLMAnalysis, dict[str, int]]:
            return (
                LLMAnalysis(
                    summary="Oil supply risk rose after a disruption.",
                    event_type="geopolitical",
                    status_assessment="reported",
                    confidence=88,
                    impact_rationale="Energy prices reacted to supply disruption risk.",
                    why_it_matters="Higher oil prices can affect inflation and energy equities.",
                    risk_flags=["single source"],
                    score_modifier=7,
                    modifier_reason="High source score and direct market relevance.",
                ),
                {"prompt_tokens": 100, "completion_tokens": 80, "total_tokens": 180},
            )

    monkeypatch.setattr(services, "llm_provider", lambda _config: FakeProvider())

    async def fake_market_move_score_for_cluster(_session, _cluster):
        return 0

    monkeypatch.setattr(
        services,
        "market_move_score_for_cluster",
        fake_market_move_score_for_cluster,
    )

    count = await services.enrich_event_clusters_with_llm(
        session,
        config=LLMConfig(enabled=True, api_key="key"),
    )

    assert count == 1
    run = next(value for value in session.added if isinstance(value, LLMAnalysisRun))
    assert run.target_type == "event_cluster"
    assert run.target_id == "evt_1"
    assert run.status == "succeeded"
    assert run.result["score_modifier"] == 7
    assert run.usage["total_tokens"] == 180


@pytest.mark.asyncio
async def test_manual_event_enrichment_can_force_low_value_event(monkeypatch) -> None:
    event = EventCluster(
        id="evt_low",
        canonical_headline="Routine market commentary",
        final_score=35,
        source_count=2,
        top_source_score=55,
        created_at=datetime(2026, 5, 27, tzinfo=UTC),
    )
    session = FakeLLMSession([event])

    class FakeProvider:
        async def analyze_event(self, _prompt: str) -> tuple[LLMAnalysis, dict[str, int]]:
            return (
                LLMAnalysis(
                    summary="Routine commentary with limited market impact.",
                    event_type="commentary",
                    status_assessment="reported",
                    confidence=70,
                    impact_rationale="No direct catalyst is visible.",
                    why_it_matters="Useful for context but not urgent.",
                    risk_flags=[],
                    score_modifier=-2,
                    modifier_reason="Low signal event.",
                ),
                {"total_tokens": 90},
            )

    async def fake_market_move_score_for_cluster(_session, _cluster):
        return 0

    monkeypatch.setattr(services, "llm_provider", lambda _config: FakeProvider())
    monkeypatch.setattr(
        services,
        "market_move_score_for_cluster",
        fake_market_move_score_for_cluster,
    )

    count = await services.enrich_event_clusters_with_llm(
        session,
        config=LLMConfig(enabled=True, api_key="key"),
        event_cluster_id="evt_low",
        force=True,
    )

    assert count == 1
    run = next(value for value in session.added if isinstance(value, LLMAnalysisRun))
    assert run.target_id == "evt_low"
    assert run.status == "succeeded"


@pytest.mark.asyncio
async def test_enrich_event_clusters_limits_concurrent_llm_calls(monkeypatch) -> None:
    events = [
        EventCluster(
            id=f"evt_{index}",
            canonical_headline=f"High value event {index}",
            final_score=90,
            source_count=1,
            top_source_score=95,
            created_at=datetime(2026, 5, 27, tzinfo=UTC),
        )
        for index in range(4)
    ]
    session = FakeLLMSession(events)

    class FakeProvider:
        def __init__(self) -> None:
            self.active_calls = 0
            self.max_active_calls = 0

        async def analyze_event(self, _prompt: str) -> tuple[LLMAnalysis, dict[str, int]]:
            self.active_calls += 1
            self.max_active_calls = max(self.max_active_calls, self.active_calls)
            await asyncio.sleep(0.01)
            self.active_calls -= 1
            return (
                LLMAnalysis(
                    summary="A high value event was analyzed.",
                    event_type="market",
                    status_assessment="reported",
                    confidence=82,
                    impact_rationale="The event has direct market relevance.",
                    why_it_matters="It can affect watched markets.",
                    risk_flags=[],
                    score_modifier=3,
                    modifier_reason="High relevance event.",
                ),
                {"total_tokens": 100},
            )

    provider = FakeProvider()
    monkeypatch.setattr(services, "llm_provider", lambda _config: provider)

    async def fake_market_move_score_for_cluster(_session, _cluster):
        return 0

    monkeypatch.setattr(
        services,
        "market_move_score_for_cluster",
        fake_market_move_score_for_cluster,
    )

    count = await services.enrich_event_clusters_with_llm(
        session,
        config=LLMConfig(enabled=True, api_key="key", max_concurrency=2),
        force=True,
    )

    assert count == 4
    assert provider.max_active_calls == 2
    runs = [value for value in session.added if isinstance(value, LLMAnalysisRun)]
    assert len(runs) == 4
    assert {run.status for run in runs} == {"succeeded"}


@pytest.mark.asyncio
async def test_enrich_event_clusters_isolates_llm_call_failures(monkeypatch) -> None:
    events = [
        EventCluster(
            id="evt_success",
            canonical_headline="Successful event",
            final_score=90,
            source_count=1,
            top_source_score=95,
            created_at=datetime(2026, 5, 27, tzinfo=UTC),
        ),
        EventCluster(
            id="evt_failure",
            canonical_headline="Failing event",
            final_score=90,
            source_count=1,
            top_source_score=95,
            created_at=datetime(2026, 5, 27, tzinfo=UTC),
        ),
    ]
    session = FakeLLMSession(events)

    class FakeProvider:
        async def analyze_event(self, prompt: str) -> tuple[LLMAnalysis, dict[str, int]]:
            if "Failing event" in prompt:
                raise ValueError("provider unavailable")
            return (
                LLMAnalysis(
                    summary="The event was analyzed.",
                    event_type="market",
                    status_assessment="reported",
                    confidence=82,
                    impact_rationale="The event has direct market relevance.",
                    why_it_matters="It can affect watched markets.",
                    risk_flags=[],
                    score_modifier=3,
                    modifier_reason="High relevance event.",
                ),
                {"total_tokens": 100},
            )

    monkeypatch.setattr(services, "llm_provider", lambda _config: FakeProvider())

    async def fake_market_move_score_for_cluster(_session, _cluster):
        return 0

    monkeypatch.setattr(
        services,
        "market_move_score_for_cluster",
        fake_market_move_score_for_cluster,
    )

    count = await services.enrich_event_clusters_with_llm(
        session,
        config=LLMConfig(enabled=True, api_key="key", max_concurrency=2),
        force=True,
    )

    assert count == 1
    runs = {run.target_id: run for run in session.added if isinstance(run, LLMAnalysisRun)}
    assert runs["evt_success"].status == "succeeded"
    assert runs["evt_failure"].status == "failed"
    assert runs["evt_failure"].error_message == "provider unavailable"


@pytest.mark.asyncio
async def test_alert_decision_includes_llm_modifier_in_score_breakdown(monkeypatch) -> None:
    event = EventCluster(
        id="evt_1",
        canonical_headline="SEC approves market structure rule",
        final_score=76,
        source_count=1,
        top_source_score=85,
        affected_entities=["SEC"],
        created_at=datetime(2026, 5, 27, tzinfo=UTC),
    )
    run = LLMAnalysisRun(
        target_type="event_cluster",
        target_id="evt_1",
        provider="openrouter",
        model="openai/gpt-4.1-mini",
        prompt_version="event-v1",
        prompt_hash="hash",
        input_snapshot={},
        result={
            "summary": "A market structure rule was approved.",
            "score_modifier": 6,
            "modifier_reason": "Official regulatory source.",
        },
        status="succeeded",
    )
    session = FakeAlertSession(event, run)

    async def fake_market_move_score_for_cluster(_session, _cluster):
        return 0

    monkeypatch.setattr(
        services,
        "market_move_score_for_cluster",
        fake_market_move_score_for_cluster,
    )

    count = await services.record_alert_decisions(session)

    assert count == 1
    alert = next(value for value in session.added if isinstance(value, AlertDecisionRecord))
    assert alert.score_breakdown["llm"]["score_modifier"] == 6
    assert alert.score_breakdown["llm"]["modifier_reason"] == "Official regulatory source."


@pytest.mark.asyncio
async def test_classify_news_item_records_classify_prompt_version(monkeypatch) -> None:
    item = NormalizedNewsItem(
        id="news_1",
        title="Vietnam bank stocks rise",
        source_name="Vietstock",
        source_type="rss",
        source_score=75,
        region="vietnam",
        asset_classes=["equity"],
        language="en",
        url="https://example.test/news",
        title_hash="title",
        normalized_text_hash="text",
    )
    session = FakeTargetSession(item)

    class FakeProvider:
        async def classify_news_item(self, _prompt: str):
            return (
                LLMClassification(
                    item_type="market_news",
                    actionability="medium",
                    event_type="credit_growth",
                    region="vietnam",
                    asset_classes=["equity"],
                    entities=["banks"],
                    tickers=[],
                    duplicate_hint="unknown",
                    confidence=80,
                    rationale="Bank equities are directly mentioned.",
                ),
                {"total_tokens": 50},
            )

    monkeypatch.setattr(services, "llm_provider", lambda _config: FakeProvider())

    run = await services.classify_news_item_with_llm(
        session,
        item_id="news_1",
        config=LLMConfig(enabled=True, api_key="key"),
        force=True,
    )

    assert run is not None
    assert run.target_type == "news_item"
    assert run.prompt_version == "classify-v1"
    assert run.result["event_type"] == "credit_growth"


@pytest.mark.asyncio
async def test_summarize_event_records_summary_prompt_version(monkeypatch) -> None:
    event = EventCluster(
        id="evt_1",
        canonical_headline="Oil jumps",
        final_score=84,
        source_count=2,
        top_source_score=85,
        status="reported",
    )
    session = FakeTargetSession(event)

    class FakeProvider:
        async def summarize_event(self, _prompt: str):
            return (
                LLMEventSummary(
                    summary="Oil jumped after a supply-risk report.",
                    status="reported",
                    affected_assets=["Brent"],
                    digest_bullets=["Crude rose on supply risk."],
                    why_it_matters="Oil can affect inflation expectations.",
                    alert_message="Oil jumps on reported supply risk.",
                    caveats=["Not official"],
                ),
                {"total_tokens": 60},
            )

    monkeypatch.setattr(services, "llm_provider", lambda _config: FakeProvider())

    run = await services.summarize_event_with_llm(
        session,
        event_cluster_id="evt_1",
        config=LLMConfig(enabled=True, api_key="key"),
        force=True,
    )

    assert run is not None
    assert run.prompt_version == "summarize-v1"
    assert run.result["digest_bullets"] == ["Crude rose on supply risk."]


@pytest.mark.asyncio
async def test_score_event_records_score_prompt_version(monkeypatch) -> None:
    event = EventCluster(
        id="evt_1",
        canonical_headline="Oil jumps",
        final_score=84,
        source_count=2,
        top_source_score=85,
        status="reported",
    )
    session = FakeTargetSession(event)

    class FakeProvider:
        async def score_event(self, _prompt: str):
            return (
                LLMEventScore(
                    impact_score=86,
                    relevance_score=75,
                    confidence_score=80,
                    risk_flags=["reported"],
                    score_modifier=5,
                    modifier_reason="Market reaction confirms impact.",
                ),
                {"total_tokens": 70},
            )

    async def fake_market_move_score_for_cluster(_session, _cluster):
        return 75

    monkeypatch.setattr(services, "llm_provider", lambda _config: FakeProvider())
    monkeypatch.setattr(
        services,
        "market_move_score_for_cluster",
        fake_market_move_score_for_cluster,
    )

    run = await services.score_event_with_llm(
        session,
        event_cluster_id="evt_1",
        config=LLMConfig(enabled=True, api_key="key"),
        force=True,
    )

    assert run is not None
    assert run.prompt_version == "score-v1"
    assert run.result["score_modifier"] == 5
