import asyncio
from datetime import UTC, datetime

import pytest

import bot_worker.services as services
import bot_worker.services.alerts as alert_services
import bot_worker.services.llm as llm_services
from bot_worker.db.models import (
    AlertDecisionRecord,
    EventCluster,
    LLMAnalysisRun,
    NewsEntity,
    NormalizedNewsItem,
)
from bot_worker.llm import (
    PROMPT_VERSION,
    LLMAnalysis,
    LLMClassification,
    LLMClusterDecision,
    LLMConfig,
    LLMEventScore,
    LLMEventSummary,
)


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

    async def execute(self, stmt):
        if "llm_analysis_runs" in str(stmt) and self.run is not None:
            return ExecuteRows([self.run])
        return ExecuteRows([])

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


class FakeClusterDecisionSession:
    def __init__(self) -> None:
        self.added: list[object] = []
        self.scalar_calls = 0

    async def scalar(self, _stmt):
        self.scalar_calls += 1
        return None

    def add(self, value: object) -> None:
        self.added.append(value)

    async def flush(self) -> None:
        return None


class FakeEntityExtractionSession:
    def __init__(
        self,
        items: list[NormalizedNewsItem],
        existing_entities: list[NewsEntity] | dict[str, list[NewsEntity]] | None = None,
        existing_runs: list[LLMAnalysisRun] | None = None,
    ) -> None:
        self.items = items
        self.existing_runs = existing_runs or []
        if isinstance(existing_entities, dict):
            self.existing_entities_by_item = existing_entities
            self.existing_entities = []
        else:
            self.existing_entities_by_item = None
            self.existing_entities = existing_entities or []
        self.added: list[object] = []
        self.deleted: list[object] = []
        self.scalar_calls = 0
        self.scalars_calls = 0

    async def scalars(self, _stmt):
        self.scalars_calls += 1
        if self.scalars_calls == 1:
            return ScalarRows(self.items)
        if self.existing_entities_by_item is not None:
            item_index = self.scalars_calls - 2
            item = self.items[item_index]
            return ScalarRows(self.existing_entities_by_item.get(item.id, []))
        return ScalarRows(self.existing_entities)

    async def get(self, _model, key: str):
        return next((item for item in self.items if item.id == key), None)

    async def scalar(self, _stmt):
        self.scalar_calls += 1
        if self.existing_runs:
            return self.existing_runs.pop(0)
        return None

    def add(self, value: object) -> None:
        self.added.append(value)

    async def execute(self, stmt):
        self.deleted.append(stmt)
        return ExecuteRows([])

    async def flush(self) -> None:
        return None


def news_item(item_id: str, title: str | None = None) -> NormalizedNewsItem:
    return NormalizedNewsItem(
        id=item_id,
        title=title or f"Market news {item_id}",
        snippet=f"Snippet for {item_id}",
        source_name="MarketWatch",
        source_type="rss",
        source_score=75,
        region="crypto",
        asset_classes=["crypto"],
        language="en",
        url=f"https://example.test/{item_id}",
        title_hash=f"title-{item_id}",
        normalized_text_hash=f"text-{item_id}",
        processing_status="normalized",
    )


def cluster_candidate_event() -> EventCluster:
    return EventCluster(
        id="evt_1",
        canonical_headline="Oil jumps after tanker incident near Hormuz",
        regions=["global"],
        asset_classes=["commodity"],
        affected_entities=["Hormuz", "Brent"],
        source_count=2,
        top_source_score=85,
    )


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
async def test_resolve_llm_cluster_decision_attaches_high_confidence_same_event(
    monkeypatch,
) -> None:
    item = news_item("news_1", title="Brent rises as Hormuz shipping risks increase")
    item.region = "global"
    item.asset_classes = ["commodity"]
    session = FakeClusterDecisionSession()

    class FakeProvider:
        async def decide_cluster_match(
            self,
            prompt: str,
        ) -> tuple[LLMClusterDecision, dict[str, int]]:
            assert "Brent rises as Hormuz" in prompt
            return (
                LLMClusterDecision(
                    decision="same_event",
                    confidence=84,
                    rationale="Both describe the same Hormuz shipping disruption.",
                ),
                {"total_tokens": 120},
            )

    monkeypatch.setattr(llm_services, "llm_provider", lambda _config: FakeProvider())

    attempted, should_attach = await llm_services.resolve_llm_cluster_decision(
        session=session,
        item=item,
        cluster=cluster_candidate_event(),
        similarity=0.87,
        config=LLMConfig(enabled=True, api_key="key"),
        entities=["Hormuz", "Brent"],
        tickers=[],
    )

    assert attempted
    assert should_attach
    run = next(value for value in session.added if isinstance(value, LLMAnalysisRun))
    assert run.target_type == "cluster_candidate"
    assert run.target_id == llm_services.cluster_candidate_target_id("news_1", "evt_1")
    assert run.prompt_version == "cluster-decision-v1"
    assert run.status == "succeeded"
    assert run.result["decision"] == "same_event"
    assert run.usage["total_tokens"] == 120


@pytest.mark.asyncio
async def test_resolve_llm_cluster_decision_rejects_low_confidence_same_event(
    monkeypatch,
) -> None:
    item = news_item("news_1", title="Brent rises as Hormuz shipping risks increase")
    session = FakeClusterDecisionSession()

    class FakeProvider:
        async def decide_cluster_match(
            self,
            _prompt: str,
        ) -> tuple[LLMClusterDecision, dict[str, int]]:
            return (
                LLMClusterDecision(
                    decision="same_event",
                    confidence=69,
                    rationale="Possibly the same incident, but not certain enough.",
                ),
                {"total_tokens": 80},
            )

    monkeypatch.setattr(llm_services, "llm_provider", lambda _config: FakeProvider())

    attempted, should_attach = await llm_services.resolve_llm_cluster_decision(
        session=session,
        item=item,
        cluster=cluster_candidate_event(),
        similarity=0.87,
        config=LLMConfig(enabled=True, api_key="key"),
        entities=["Hormuz"],
        tickers=[],
    )

    assert attempted
    assert not should_attach
    run = next(value for value in session.added if isinstance(value, LLMAnalysisRun))
    assert run.status == "succeeded"
    assert run.result["confidence"] == 69


@pytest.mark.asyncio
async def test_resolve_llm_cluster_decision_fails_open_on_provider_error(monkeypatch) -> None:
    item = news_item("news_1", title="Brent rises as Hormuz shipping risks increase")
    session = FakeClusterDecisionSession()

    class FakeProvider:
        async def decide_cluster_match(self, _prompt: str):
            raise ValueError("provider unavailable")

    monkeypatch.setattr(llm_services, "llm_provider", lambda _config: FakeProvider())

    attempted, should_attach = await llm_services.resolve_llm_cluster_decision(
        session=session,
        item=item,
        cluster=cluster_candidate_event(),
        similarity=0.87,
        config=LLMConfig(enabled=True, api_key="key"),
        entities=["Hormuz"],
        tickers=[],
    )

    assert attempted
    assert not should_attach
    run = next(value for value in session.added if isinstance(value, LLMAnalysisRun))
    assert run.status == "failed"
    assert run.error_message == "provider unavailable"


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
                    alert_message="Oil jumps after reported Hormuz disruption.",
                    risk_flags=["single source"],
                    score_modifier=7,
                    modifier_reason="High source score and direct market relevance.",
                ),
                {"prompt_tokens": 100, "completion_tokens": 80, "total_tokens": 180},
            )

    monkeypatch.setattr(llm_services, "llm_provider", lambda _config: FakeProvider())

    async def fake_market_move_score_for_cluster(_session, _cluster):
        return 0

    monkeypatch.setattr(
        llm_services,
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
    assert run.result["alert_message"] == "Oil jumps after reported Hormuz disruption."
    assert run.result["score_modifier"] == 7
    assert run.usage["total_tokens"] == 180


@pytest.mark.asyncio
async def test_enrich_event_clusters_clamps_modifier_with_config(monkeypatch) -> None:
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
                    alert_message="Oil jumps after reported Hormuz disruption.",
                    risk_flags=["single source"],
                    score_modifier=7,
                    modifier_reason="High source score and direct market relevance.",
                ),
                {"total_tokens": 180},
            )

    async def fake_market_move_score_for_cluster(_session, _cluster):
        return 0

    monkeypatch.setattr(llm_services, "llm_provider", lambda _config: FakeProvider())
    monkeypatch.setattr(
        llm_services,
        "market_move_score_for_cluster",
        fake_market_move_score_for_cluster,
    )

    count = await services.enrich_event_clusters_with_llm(
        session,
        config=LLMConfig(enabled=True, api_key="key", max_modifier=5),
    )

    assert count == 1
    run = next(value for value in session.added if isinstance(value, LLMAnalysisRun))
    assert run.result["score_modifier"] == 5


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
                    alert_message="Routine market commentary has limited urgency.",
                    risk_flags=[],
                    score_modifier=-2,
                    modifier_reason="Low signal event.",
                ),
                {"total_tokens": 90},
            )

    async def fake_market_move_score_for_cluster(_session, _cluster):
        return 0

    monkeypatch.setattr(llm_services, "llm_provider", lambda _config: FakeProvider())
    monkeypatch.setattr(
        llm_services,
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
                    alert_message="A high value market event was analyzed.",
                    risk_flags=[],
                    score_modifier=3,
                    modifier_reason="High relevance event.",
                ),
                {"total_tokens": 100},
            )

    provider = FakeProvider()
    monkeypatch.setattr(llm_services, "llm_provider", lambda _config: provider)

    async def fake_market_move_score_for_cluster(_session, _cluster):
        return 0

    monkeypatch.setattr(
        llm_services,
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
                    alert_message="The market event was analyzed.",
                    risk_flags=[],
                    score_modifier=3,
                    modifier_reason="High relevance event.",
                ),
                {"total_tokens": 100},
            )

    monkeypatch.setattr(llm_services, "llm_provider", lambda _config: FakeProvider())

    async def fake_market_move_score_for_cluster(_session, _cluster):
        return 0

    monkeypatch.setattr(
        llm_services,
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
        prompt_version=PROMPT_VERSION,
        prompt_hash="hash",
        input_snapshot={},
        result={
            "summary": "A market structure rule was approved.",
            "alert_message": "SEC approves a reported market structure rule.",
            "why_it_matters": "The rule can affect exchange and broker operations.",
            "score_modifier": 6,
            "modifier_reason": "Official regulatory source.",
        },
        status="succeeded",
    )
    session = FakeAlertSession(event, run)

    async def fake_market_move_score_for_cluster(_session, _cluster):
        return 0

    monkeypatch.setattr(
        alert_services,
        "market_move_score_for_cluster",
        fake_market_move_score_for_cluster,
        raising=False,
    )

    count = await services.record_alert_decisions(session)

    assert count == 1
    alert = next(value for value in session.added if isinstance(value, AlertDecisionRecord))
    assert alert.score_breakdown["llm"]["alert_message"] == (
        "SEC approves a reported market structure rule."
    )
    assert alert.score_breakdown["llm"]["why_it_matters"] == (
        "The rule can affect exchange and broker operations."
    )
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
                    confidence=80,
                    rationale="Bank equities are directly mentioned.",
                ),
                {"total_tokens": 50},
            )

    monkeypatch.setattr(llm_services, "llm_provider", lambda _config: FakeProvider())

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
async def test_extract_entities_with_llm_persists_news_entities_without_watchlist(
    monkeypatch,
) -> None:
    item = news_item(
        "news_1",
        "Bitcoin options are coming to Nasdaq. Here's what it means for you.",
    )
    session = FakeEntityExtractionSession([item])

    class FakeProvider:
        async def classify_news_item(self, _prompt: str):
            return (
                LLMClassification(
                    item_type="market_news",
                    actionability="medium",
                    event_type="exchange_product",
                    region="crypto",
                    asset_classes=["crypto"],
                    entities=["Bitcoin"],
                    tickers=["BTC"],
                    confidence=86,
                    rationale="Bitcoin is the only affected asset in the headline.",
                ),
                {"total_tokens": 60},
            )

    monkeypatch.setattr(llm_services, "llm_provider", lambda _config: FakeProvider())

    count = await services.extract_entities_with_llm(
        session,
        config=LLMConfig(enabled=True, api_key="key"),
    )

    entities = [value for value in session.added if isinstance(value, NewsEntity)]
    runs = [value for value in session.added if isinstance(value, LLMAnalysisRun)]
    assert count == 1
    assert len(runs) == 1
    assert len(entities) == 2
    assert {entity.normalized_name for entity in entities} == {"Bitcoin", "BTC"}
    bitcoin = next(entity for entity in entities if entity.normalized_name == "Bitcoin")
    btc = next(entity for entity in entities if entity.normalized_name == "BTC")
    assert bitcoin.entity_type == "market_entity"
    assert bitcoin.ticker is None
    assert bitcoin.confidence == 86
    assert btc.entity_type == "ticker"
    assert btc.ticker == "BTC"


@pytest.mark.asyncio
async def test_extract_entities_with_llm_does_not_persist_long_ticker_phrases(
    monkeypatch,
) -> None:
    item = news_item("news_1", "OpenAI and Anthropic compete before IPO")
    session = FakeEntityExtractionSession([item])

    long_phrase = "OpenAI and Anthropic (competition for IPO)"

    class FakeProvider:
        async def classify_news_item(self, _prompt: str):
            return (
                LLMClassification(
                    item_type="market_news",
                    actionability="medium",
                    event_type="ipo_competition",
                    region="us",
                    asset_classes=["equity"],
                    entities=[],
                    tickers=[long_phrase],
                    confidence=83,
                    rationale="The phrase is an entity, not a ticker.",
                ),
                {"total_tokens": 60},
            )

    monkeypatch.setattr(llm_services, "llm_provider", lambda _config: FakeProvider())

    count = await services.extract_entities_with_llm(
        session,
        config=LLMConfig(enabled=True, api_key="key"),
    )

    entities = [value for value in session.added if isinstance(value, NewsEntity)]
    assert count == 1
    assert len(entities) == 1
    assert entities[0].entity_type == "market_entity"
    assert entities[0].normalized_name == long_phrase
    assert entities[0].ticker is None


@pytest.mark.asyncio
async def test_extract_entities_with_llm_caps_overlong_entity_strings(monkeypatch) -> None:
    item = news_item("news_1", "Long entity")
    session = FakeEntityExtractionSession([item])
    overlong_entity = "A" * 300

    class FakeProvider:
        async def classify_news_item(self, _prompt: str):
            return (
                LLMClassification(
                    item_type="market_news",
                    actionability="medium",
                    event_type="market_update",
                    region="global",
                    asset_classes=["equity"],
                    entities=[overlong_entity],
                    tickers=[],
                    confidence=80,
                    rationale="The item mentions a long entity name.",
                ),
                {"total_tokens": 60},
            )

    monkeypatch.setattr(llm_services, "llm_provider", lambda _config: FakeProvider())

    await services.extract_entities_with_llm(
        session,
        config=LLMConfig(enabled=True, api_key="key"),
    )

    entities = [value for value in session.added if isinstance(value, NewsEntity)]
    assert len(entities) == 1
    assert len(entities[0].raw_text) == 255
    assert len(entities[0].normalized_name) == 255


@pytest.mark.asyncio
async def test_extract_entities_with_llm_sanitizes_completed_cached_runs() -> None:
    item = news_item("news_1", "Cached classification")
    cached_run = LLMAnalysisRun(
        target_type="news_item",
        target_id=item.id,
        provider="openrouter",
        model="openai/gpt-4.1-mini",
        prompt_version="classify-v1",
        prompt_hash="hash",
        status="succeeded",
        result={
            "entities": ["A" * 300],
            "tickers": ["OpenAI and Anthropic (competition for IPO)"],
            "confidence": 82,
        },
    )
    session = FakeEntityExtractionSession([item], existing_runs=[cached_run])

    count = await services.extract_entities_with_llm(
        session,
        config=LLMConfig(enabled=True, api_key="key"),
    )

    entities = [value for value in session.added if isinstance(value, NewsEntity)]
    assert count == 1
    assert len(entities) == 2
    assert all(entity.ticker is None for entity in entities)
    assert all(len(entity.raw_text) <= 255 for entity in entities)
    assert all(len(entity.normalized_name) <= 255 for entity in entities)


@pytest.mark.asyncio
async def test_extract_entities_with_llm_limits_concurrent_classification_calls(
    monkeypatch,
) -> None:
    items = [news_item(f"news_{index}") for index in range(4)]
    session = FakeEntityExtractionSession(items, existing_entities={item.id: [] for item in items})

    class FakeProvider:
        def __init__(self) -> None:
            self.active_calls = 0
            self.max_active_calls = 0

        async def classify_news_item(self, prompt: str):
            self.active_calls += 1
            self.max_active_calls = max(self.max_active_calls, self.active_calls)
            await asyncio.sleep(0.01)
            self.active_calls -= 1
            item_id = next(item.id for item in items if item.id in prompt)
            return (
                LLMClassification(
                    item_type="market_news",
                    actionability="medium",
                    event_type="exchange_product",
                    region="crypto",
                    asset_classes=["crypto"],
                    entities=[f"Entity {item_id}"],
                    tickers=[],
                    confidence=80,
                    rationale="The item mentions a market entity.",
                ),
                {"total_tokens": 60},
            )

    provider = FakeProvider()
    monkeypatch.setattr(llm_services, "llm_provider", lambda _config: provider)

    count = await services.extract_entities_with_llm(
        session,
        config=LLMConfig(enabled=True, api_key="key", max_concurrency=2),
    )

    entities = [value for value in session.added if isinstance(value, NewsEntity)]
    runs = [value for value in session.added if isinstance(value, LLMAnalysisRun)]
    assert count == 4
    assert provider.max_active_calls == 2
    assert len(entities) == 4
    assert len(runs) == 4
    assert {run.status for run in runs} == {"succeeded"}


@pytest.mark.asyncio
async def test_extract_entities_with_llm_isolates_classification_failures(monkeypatch) -> None:
    items = [
        news_item("news_success", "Successful classification"),
        news_item("news_failure", "Failing classification"),
    ]
    session = FakeEntityExtractionSession(items, existing_entities={item.id: [] for item in items})

    class FakeProvider:
        async def classify_news_item(self, prompt: str):
            if "news_failure" in prompt:
                raise ValueError("provider unavailable")
            return (
                LLMClassification(
                    item_type="market_news",
                    actionability="medium",
                    event_type="exchange_product",
                    region="crypto",
                    asset_classes=["crypto"],
                    entities=["Bitcoin"],
                    tickers=["BTC"],
                    confidence=86,
                    rationale="Bitcoin is the affected asset.",
                ),
                {"total_tokens": 60},
            )

    monkeypatch.setattr(llm_services, "llm_provider", lambda _config: FakeProvider())

    count = await services.extract_entities_with_llm(
        session,
        config=LLMConfig(enabled=True, api_key="key", max_concurrency=2),
    )

    runs = {run.target_id: run for run in session.added if isinstance(run, LLMAnalysisRun)}
    entities = [value for value in session.added if isinstance(value, NewsEntity)]
    assert count == 1
    assert runs["news_success"].status == "succeeded"
    assert runs["news_failure"].status == "failed"
    assert runs["news_failure"].error_message == "provider unavailable"
    assert {entity.news_item_id for entity in entities} == {"news_success"}


@pytest.mark.asyncio
async def test_extract_entities_with_llm_skips_existing_entities_without_force(
    monkeypatch,
) -> None:
    item = news_item("news_existing")
    session = FakeEntityExtractionSession(
        [item],
        existing_entities={
            item.id: [
                NewsEntity(
                    news_item_id=item.id,
                    entity_type="market_entity",
                    raw_text="Bitcoin",
                    normalized_name="Bitcoin",
                    confidence=80,
                )
            ]
        },
    )

    class FakeProvider:
        async def classify_news_item(self, _prompt: str):
            raise AssertionError("provider should not be called")

    monkeypatch.setattr(llm_services, "llm_provider", lambda _config: FakeProvider())

    count = await services.extract_entities_with_llm(
        session,
        config=LLMConfig(enabled=True, api_key="key"),
    )

    assert count == 0
    assert session.added == []
    assert session.deleted == []


@pytest.mark.asyncio
async def test_extract_entities_with_llm_force_deletes_existing_entities_and_reclassifies(
    monkeypatch,
) -> None:
    item = news_item("news_existing")
    session = FakeEntityExtractionSession(
        [item],
        existing_entities={
            item.id: [
                NewsEntity(
                    news_item_id=item.id,
                    entity_type="market_entity",
                    raw_text="Old entity",
                    normalized_name="Old entity",
                    confidence=70,
                )
            ]
        },
    )

    class FakeProvider:
        async def classify_news_item(self, _prompt: str):
            return (
                LLMClassification(
                    item_type="market_news",
                    actionability="medium",
                    event_type="exchange_product",
                    region="crypto",
                    asset_classes=["crypto"],
                    entities=["Bitcoin"],
                    tickers=[],
                    confidence=86,
                    rationale="Bitcoin is the affected asset.",
                ),
                {"total_tokens": 60},
            )

    monkeypatch.setattr(llm_services, "llm_provider", lambda _config: FakeProvider())

    count = await services.extract_entities_with_llm(
        session,
        config=LLMConfig(enabled=True, api_key="key"),
        force=True,
    )

    entities = [value for value in session.added if isinstance(value, NewsEntity)]
    assert count == 1
    assert len(session.deleted) == 1
    assert len(entities) == 1
    assert entities[0].normalized_name == "Bitcoin"


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

    monkeypatch.setattr(llm_services, "llm_provider", lambda _config: FakeProvider())

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

    monkeypatch.setattr(llm_services, "llm_provider", lambda _config: FakeProvider())
    monkeypatch.setattr(
        llm_services,
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
