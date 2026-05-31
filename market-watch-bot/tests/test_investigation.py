import json
from datetime import UTC, datetime

import pytest

import bot_worker.services.alerts as alert_services
import bot_worker.services.investigation as investigation_services
from bot_worker.db.models import (
    AgentInvestigation,
    AlertDecisionRecord,
    EventCluster,
    MarketMove,
    MissedCatalystReview,
    NormalizedNewsItem,
)
from bot_worker.investigation import (
    BraveSearchClient,
    BraveSearchResult,
    InvestigationConfig,
    should_queue_event_investigation,
    should_queue_missed_catalyst_investigation,
)
from bot_worker.llm import LLMConfig, LLMInvestigationResult


class ScalarRows:
    def __init__(self, rows: list[object]) -> None:
        self.rows = rows

    def all(self) -> list[object]:
        return self.rows


class FakeInvestigationSession:
    def __init__(self, target: object, existing: AgentInvestigation | None = None) -> None:
        self.target = target
        self.existing = existing
        self.added: list[object] = []
        self.flushed = 0

    async def get(self, _model, _key):
        return self.target

    async def scalar(self, _stmt):
        return self.existing

    async def scalars(self, _stmt):
        return ScalarRows([])

    def add(self, value: object) -> None:
        self.added.append(value)

    async def flush(self) -> None:
        self.flushed += 1


class FakeAlertSession:
    def __init__(
        self,
        event: EventCluster,
        investigation: AgentInvestigation | None = None,
    ) -> None:
        self.event = event
        self.investigation = investigation
        self.added: list[object] = []
        self.scalar_calls = 0
        self.scalars_calls = 0

    async def scalars(self, _stmt):
        self.scalars_calls += 1
        if self.scalars_calls == 1:
            return ScalarRows([self.event])
        return ScalarRows([])

    async def scalar(self, _stmt):
        self.scalar_calls += 1
        if self.scalar_calls == 1:
            return None
        return self.investigation

    def add(self, value: object) -> None:
        self.added.append(value)


class FakeEvidenceSession:
    def __init__(self, rows: list[NormalizedNewsItem]) -> None:
        self.rows = rows
        self.statements: list[object] = []

    async def scalars(self, stmt):
        self.statements.append(stmt)
        return ScalarRows(self.rows)


class PendingSession:
    def __init__(self, rows: list[AgentInvestigation]) -> None:
        self.rows = rows
        self.added: list[object] = []
        self.flushed = 0

    async def scalars(self, _stmt):
        if "agent_investigations" in str(_stmt):
            return ScalarRows(self.rows)
        return ScalarRows([])

    def add(self, value: object) -> None:
        self.added.append(value)

    async def flush(self) -> None:
        self.flushed += 1


def event(**overrides: object) -> EventCluster:
    values = {
        "id": "evt_1",
        "canonical_headline": "Oil jumps after reported Gulf shipping disruption",
        "summary": "Oil prices rose after an unconfirmed shipping disruption.",
        "status": "reported",
        "regions": ["global"],
        "asset_classes": ["commodity"],
        "affected_entities": ["Brent"],
        "affected_tickers": ["USO"],
        "source_count": 1,
        "top_source_score": 92,
        "final_score": 82,
        "created_at": datetime(2026, 5, 28, tzinfo=UTC),
    }
    values.update(overrides)
    return EventCluster(**values)


def news_item(
    item_id: str,
    *,
    title: str,
    snippet: str = "USO related snippet",
    source_score: int = 70,
) -> NormalizedNewsItem:
    return NormalizedNewsItem(
        id=item_id,
        source_id="src_1",
        title=title,
        snippet=snippet,
        url=f"https://example.test/{item_id}",
        source_name="Example",
        source_type="rss",
        source_score=source_score,
        region="global",
        asset_classes=["commodity"],
        title_hash=f"title-{item_id}",
        normalized_text_hash=f"text-{item_id}",
        created_at=datetime(2026, 5, 28, tzinfo=UTC),
    )


def test_event_investigation_trigger_selects_high_value_uncertain_events() -> None:
    config = InvestigationConfig(enabled=True)

    assert should_queue_event_investigation(event(), config=config)
    assert should_queue_event_investigation(
        event(final_score=58, source_count=1, top_source_score=96),
        config=config,
    )
    assert not should_queue_event_investigation(
        event(final_score=45, source_count=4, top_source_score=70, status="confirmed"),
        config=config,
    )
    
    # Test configurable rumor threshold
    config_high = InvestigationConfig(
        enabled=True,
        auto_event_score_threshold=90,
        auto_single_source_score_threshold=95,
        auto_rumor_score_threshold=85,
    )
    assert not should_queue_event_investigation(
        event(final_score=82, status="reported"), config=config_high
    )
    assert should_queue_event_investigation(
        event(final_score=86, status="reported"), config=config_high
    )


def test_pending_missed_catalyst_review_queues_investigation() -> None:
    config = InvestigationConfig(enabled=True)
    review = MissedCatalystReview(
        id="review_1",
        asset_symbol="BTC",
        asset_class="crypto",
        move_window="1d",
        price_change_pct=8.4,
        volume_change_pct=120,
        status="pending",
    )

    assert should_queue_missed_catalyst_investigation(review, config=config)
    review.status = "resolved"
    assert not should_queue_missed_catalyst_investigation(review, config=config)


@pytest.mark.asyncio
async def test_run_event_investigation_stores_json_serializable_snapshot(monkeypatch) -> None:
    target = event()
    session = FakeInvestigationSession(target)

    class FakeProvider:
        async def investigate_event(self, _prompt: str):
            return (
                LLMInvestigationResult(
                    summary="Checked.",
                    confidence=70,
                    official_confirmation="unconfirmed",
                    risk_flags=[],
                    suggested_score_modifier=0,
                    suggested_alert_level="daily_digest",
                    caveats=[],
                ),
                {},
            )

    class FakeSearch:
        async def search(self, _query: str, *, count: int):
            return []

    monkeypatch.setattr(investigation_services, "llm_provider", lambda _config: FakeProvider())

    run = await investigation_services.run_event_investigation(
        session,
        event_id="evt_1",
        config=InvestigationConfig(enabled=True, brave_search_api_key="brave-key"),
        llm_config=LLMConfig(enabled=True, api_key="llm-key"),
        search_client=FakeSearch(),
    )

    json.dumps(run.input_snapshot)
    assert run.input_snapshot["created_at"] == "2026-05-28T00:00:00+00:00"


@pytest.mark.asyncio
async def test_brave_search_client_normalizes_web_results() -> None:
    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {
                "web": {
                    "results": [
                        {
                            "title": "Exchange statement",
                            "url": "https://www.sec.gov/news/press-release/example",
                            "description": "Official statement text",
                        }
                    ]
                }
            }

    class FakeHttpClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def get(self, url, *, params, headers):
            assert url == "https://api.search.brave.com/res/v1/web/search"
            assert params["q"] == "BTC catalyst"
            assert headers["X-Subscription-Token"] == "brave-key"
            return FakeResponse()

    client = BraveSearchClient(
        api_key="brave-key",
        http_client_factory=lambda **_: FakeHttpClient(),
    )

    results = await client.search("BTC catalyst", count=3)

    assert results[0].title == "Exchange statement"
    assert results[0].url == "https://www.sec.gov/news/press-release/example"
    assert results[0].source_quality == "official"


@pytest.mark.asyncio
async def test_gather_investigation_evidence_uses_configured_local_limits() -> None:
    session = FakeEvidenceSession(
        [
            news_item("news_1", title="USO jumps on oil move"),
            news_item("news_2", title="USO tracks crude higher"),
        ]
    )

    evidence = await investigation_services.gather_investigation_evidence(
        session,
        snapshot={"affected_tickers": ["USO"]},
        config=InvestigationConfig(
            enabled=True,
            local_evidence_limit=2,
            local_evidence_lookback_days=14,
        ),
    )

    assert len(evidence) == 2
    stmt_text = str(session.statements[0])
    assert "LIMIT :param_1" in stmt_text


@pytest.mark.asyncio
async def test_local_evidence_scores_context_and_filters_weak_symbol_matches() -> None:
    session = FakeEvidenceSession(
        [
            news_item(
                "news_weak",
                title="USO drifts lower with broader ETF flows",
                snippet="Passive fund rotation weighs on trading.",
                source_score=60,
            ),
            news_item(
                "news_strong",
                title="USO rises as Gulf shipping disruption lifts oil",
                snippet="Brent reacts to reported Gulf disruption.",
                source_score=95,
            ),
            news_item(
                "news_medium",
                title="Oil traders watch Gulf disruption risk",
                snippet="USO and Brent remain sensitive.",
                source_score=70,
            ),
        ]
    )

    evidence = await investigation_services.gather_investigation_evidence(
        session,
        snapshot={
            "headline": "Oil jumps after reported Gulf shipping disruption",
            "summary": "Oil prices rose after an unconfirmed shipping disruption.",
            "affected_entities": ["Brent"],
            "affected_tickers": ["USO"],
        },
        config=InvestigationConfig(enabled=True, local_evidence_limit=10),
    )

    assert [item["news_item_id"] for item in evidence] == ["news_strong", "news_medium"]
    assert evidence[0]["relevance_score"] > evidence[1]["relevance_score"]


@pytest.mark.asyncio
async def test_gather_event_evidence_runs_official_query_and_ranks_deduped_results() -> None:
    session = FakeEvidenceSession([])

    class FakeSearch:
        def __init__(self) -> None:
            self.queries: list[tuple[str, int]] = []

        async def search(self, query: str, *, count: int):
            self.queries.append((query, count))
            if "official" in query:
                return [
                    BraveSearchResult(
                        title="Official regulator record",
                        url="https://www.sec.gov/news/example",
                        description="Official source",
                        source_quality="official",
                    ),
                    BraveSearchResult(
                        title="Duplicate regulator record",
                        url="https://www.sec.gov/other/example",
                        description="Same domain duplicate",
                        source_quality="official",
                    ),
                ]
            return [
                BraveSearchResult(
                    title="Media report",
                    url="https://example-news.test/story",
                    description="Media source",
                    source_quality="media",
                ),
                BraveSearchResult(
                    title="Repeated media report",
                    url="https://example-news.test/story",
                    description="Duplicate URL",
                    source_quality="media",
                ),
                BraveSearchResult(
                    title="Reuters report",
                    url="https://www.reuters.com/markets/story",
                    description="High quality source",
                    source_quality="high_quality",
                ),
            ]

    search = FakeSearch()

    evidence = await investigation_services.gather_investigation_evidence(
        session,
        snapshot={
            "headline": "SEC approves sample product",
            "affected_entities": ["SEC"],
            "affected_tickers": [],
        },
        config=InvestigationConfig(
            enabled=True,
            max_search_results=10,
            max_evidence_items=3,
        ),
        search_client=search,
    )

    assert search.queries == [
        ("SEC approves sample product", 10),
        ("SEC official regulator filing announcement", 10),
    ]
    assert [item["source_quality"] for item in evidence] == [
        "official",
        "high_quality",
        "media",
    ]
    assert [item["url"] for item in evidence] == [
        "https://www.sec.gov/news/example",
        "https://www.reuters.com/markets/story",
        "https://example-news.test/story",
    ]


@pytest.mark.asyncio
async def test_run_event_investigation_stores_structured_recommendation(monkeypatch) -> None:
    target = event()
    session = FakeInvestigationSession(target)

    class FakeProvider:
        async def investigate_event(self, prompt: str):
            assert "Oil jumps" in prompt
            return (
                LLMInvestigationResult(
                    summary="Official confirmation is not yet present.",
                    confidence=72,
                    official_confirmation="unconfirmed",
                    risk_flags=["single_source"],
                    suggested_score_modifier=-4,
                    suggested_alert_level="watchlist_batch",
                    caveats=["Search found no official source."],
                ),
                {"total_tokens": 321},
            )

    class FakeSearch:
        async def search(self, query: str, *, count: int):
            assert query in {
                "Oil jumps after reported Gulf shipping disruption",
                "Brent official regulator filing announcement",
            }
            return []

    monkeypatch.setattr(investigation_services, "llm_provider", lambda _config: FakeProvider())

    run = await investigation_services.run_event_investigation(
        session,
        event_id="evt_1",
        config=InvestigationConfig(enabled=True, brave_search_api_key="brave-key"),
        llm_config=LLMConfig(enabled=True, api_key="llm-key"),
        search_client=FakeSearch(),
    )

    assert run.status == "succeeded"
    assert run.target_type == "event_cluster"
    assert run.target_id == "evt_1"
    assert run.result["suggested_score_modifier"] == -4
    assert run.usage == {"total_tokens": 321}


@pytest.mark.asyncio
async def test_alert_decision_applies_latest_investigation_modifier() -> None:
    investigation = AgentInvestigation(
        id="inv_1",
        target_type="event_cluster",
        target_id="evt_1",
        trigger_reason="manual",
        status="succeeded",
        input_snapshot={},
        evidence=[],
        provider="openrouter",
        model="model",
        prompt_version="investigation-v1",
        prompt_hash="hash",
        result={
            "summary": "No official confirmation found.",
            "confidence": 80,
            "official_confirmation": "unconfirmed",
            "risk_flags": ["single_source"],
            "suggested_score_modifier": -5,
            "suggested_alert_level": "watchlist_batch",
            "caveats": [],
        },
    )
    session = FakeAlertSession(event(), investigation=investigation)

    count = await alert_services.record_alert_decisions(session)

    assert count == 1
    alert = next(item for item in session.added if isinstance(item, AlertDecisionRecord))
    assert alert.score_breakdown["investigation"]["run_id"] == "inv_1"
    assert alert.score_breakdown["investigation"]["suggested_score_modifier"] == -5
    assert alert.score_breakdown["final_score"] == alert.score_breakdown[
        "deterministic_final_score"
    ] - 5


@pytest.mark.asyncio
async def test_run_move_investigation_uses_market_move_snapshot(monkeypatch) -> None:
    move = MarketMove(
        id="move_1",
        asset_symbol="BTC",
        asset_class="crypto",
        timestamp=datetime(2026, 5, 28, tzinfo=UTC),
        window="1d",
        price_change_pct=8.4,
        volume_change_pct=120,
    )
    session = FakeInvestigationSession(move)

    class FakeProvider:
        async def investigate_event(self, prompt: str):
            assert "BTC" in prompt
            return (
                LLMInvestigationResult(
                    summary="Move appears catalyst-linked but unconfirmed.",
                    confidence=65,
                    official_confirmation="unconfirmed",
                    risk_flags=[],
                    suggested_score_modifier=0,
                    suggested_alert_level="daily_digest",
                    caveats=[],
                ),
                {},
            )

    class FakeSearch:
        async def search(self, query: str, *, count: int):
            assert "BTC" in query
            return []

    monkeypatch.setattr(investigation_services, "llm_provider", lambda _config: FakeProvider())

    run = await investigation_services.run_move_investigation(
        session,
        move_id="move_1",
        config=InvestigationConfig(enabled=True, brave_search_api_key="brave-key"),
        llm_config=LLMConfig(enabled=True, api_key="llm-key"),
        search_client=FakeSearch(),
    )

    assert run.target_type == "market_move"
    assert run.input_snapshot["asset_symbol"] == "BTC"


@pytest.mark.asyncio
async def test_run_existing_investigation_uses_pending_row_without_creating_duplicate(
    monkeypatch,
) -> None:
    run = AgentInvestigation(
        id="inv_1",
        target_type="event_cluster",
        target_id="evt_1",
        trigger_reason="auto_event_uncertain",
        status="pending",
        input_snapshot={
            "headline": "Oil jumps",
            "affected_entities": ["Brent"],
            "affected_tickers": ["USO"],
        },
        evidence=[],
    )
    session = PendingSession([run])

    class FakeProvider:
        async def investigate_event(self, _prompt: str):
            return (
                LLMInvestigationResult(
                    summary="Checked.",
                    confidence=70,
                    official_confirmation="unconfirmed",
                    risk_flags=[],
                    suggested_score_modifier=3,
                    suggested_alert_level="immediate_alert",
                    caveats=[],
                ),
                {"total_tokens": 12},
            )

    monkeypatch.setattr(investigation_services, "llm_provider", lambda _config: FakeProvider())

    result = await investigation_services.run_existing_investigation(
        session,
        run,
        config=InvestigationConfig(enabled=True),
        llm_config=LLMConfig(enabled=True, api_key="llm-key"),
    )

    assert result is run
    assert session.added == []
    assert run.status == "succeeded"
    assert run.result["suggested_score_modifier"] == 3


@pytest.mark.asyncio
async def test_run_pending_investigations_counts_success_failure_and_unsupported(
    monkeypatch,
) -> None:
    rows = [
        AgentInvestigation(
            id="inv_success",
            target_type="event_cluster",
            target_id="evt_1",
            trigger_reason="auto_event_uncertain",
            status="pending",
            input_snapshot={"headline": "Oil jumps"},
            evidence=[],
        ),
        AgentInvestigation(
            id="inv_fail",
            target_type="asset",
            target_id="BTC",
            trigger_reason="manual",
            status="pending",
            input_snapshot={"asset_symbol": "BTC"},
            evidence=[],
        ),
        AgentInvestigation(
            id="inv_bad",
            target_type="unknown",
            target_id="x",
            trigger_reason="manual",
            status="pending",
            input_snapshot={},
            evidence=[],
        ),
    ]
    session = PendingSession(rows)

    async def fake_run_concurrently(_session, runs, *, config, llm_config, search_client=None):
        for run in runs:
            if run.id == "inv_success":
                run.status = "succeeded"
            elif run.id == "inv_fail":
                run.status = "failed"
            else:
                run.status = "failed"
                run.error_message = "Unsupported investigation target type: unknown"
        return {"completed": 1, "failed": 2}

    monkeypatch.setattr(
        investigation_services,
        "run_investigations_concurrently",
        fake_run_concurrently,
    )

    result = await investigation_services.run_pending_investigations(
        session,
        config=InvestigationConfig(enabled=True),
        llm_config=LLMConfig(enabled=True, api_key="llm-key"),
        limit=10,
    )

    assert result == {"pending": 3, "completed": 1, "failed": 2}
    assert rows[2].status == "failed"
    assert "Unsupported investigation target type" in rows[2].error_message


@pytest.mark.asyncio
async def test_queue_missed_catalyst_investigations_skips_existing_run() -> None:
    review = MissedCatalystReview(
        id="review_1",
        asset_symbol="BTC",
        asset_class="crypto",
        move_window="1d",
        price_change_pct=8.4,
        volume_change_pct=120,
        status="pending",
    )
    existing = AgentInvestigation(
        id="inv_1",
        target_type="missed_catalyst_review",
        target_id="review_1",
        trigger_reason="auto_missed_catalyst",
        status="pending",
        input_snapshot={},
        evidence=[],
    )

    class ReviewSession:
        def __init__(self) -> None:
            self.added: list[object] = []
            self.scalar_calls = 0

        async def scalars(self, _stmt):
            return ScalarRows([review])

        async def scalar(self, _stmt):
            self.scalar_calls += 1
            return existing

        def add(self, value: object) -> None:
            self.added.append(value)

        async def flush(self) -> None:
            return None

    session = ReviewSession()

    count = await investigation_services.queue_investigations_for_missed_catalysts(
        session,
        config=InvestigationConfig(enabled=True),
    )

    assert count == 0
    assert session.added == []


@pytest.mark.asyncio
async def test_run_existing_investigation_records_db_failure_without_pending_rollback(
    monkeypatch,
) -> None:
    run = AgentInvestigation(
        id="inv_1",
        target_type="event_cluster",
        target_id="evt_1",
        trigger_reason="auto_event_uncertain",
        status="pending",
        input_snapshot={"headline": "Oil jumps", "affected_tickers": ["USO"]},
        evidence=[],
    )

    class Nested:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

    class BrokenSession(PendingSession):
        def begin_nested(self):
            return Nested()

        async def scalars(self, _stmt):
            raise RuntimeError("database read failed")

    async def unexpected_search(*_args, **_kwargs):
        raise AssertionError("search should not run after local DB failure")

    monkeypatch.setattr(investigation_services, "llm_provider", lambda _config: None)
    session = BrokenSession([run])

    result = await investigation_services.run_existing_investigation(
        session,
        run,
        config=InvestigationConfig(enabled=True),
        llm_config=LLMConfig(enabled=True, api_key="llm-key"),
        search_client=type("Search", (), {"search": unexpected_search})(),
    )

    assert result.status == "failed"
    assert "database read failed" in result.error_message


@pytest.mark.asyncio
async def test_brave_search_client_uses_custom_official_and_high_quality_domains() -> None:
    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {
                "web": {
                    "results": [
                        {
                            "title": "Custom official",
                            "url": "https://custom-official.com/announcement",
                            "description": "Custom official announcement",
                        },
                        {
                            "title": "Custom high quality",
                            "url": "https://custom-hq.com/article",
                            "description": "Custom HQ article",
                        },
                        {
                            "title": "Standard official",
                            "url": "https://www.sec.gov/news/press-release",
                            "description": "Standard SEC news",
                        }
                    ]
                }
            }

    class FakeHttpClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def get(self, url, *, params, headers):
            return FakeResponse()

    # Use standard default fallback domains first:
    client_default = BraveSearchClient(
        api_key="brave-key",
        http_client_factory=lambda **_: FakeHttpClient(),
    )
    results_default = await client_default.search("test", count=3)
    assert results_default[0].source_quality == "media"  # not in default domains
    assert results_default[1].source_quality == "media"  # not in default domains
    assert results_default[2].source_quality == "official"  # sec.gov in default domains

    # Now use custom defined domains:
    client_custom = BraveSearchClient(
        api_key="brave-key",
        http_client_factory=lambda **_: FakeHttpClient(),
        official_domains=("custom-official.com",),
        high_quality_domains=("custom-hq.com",),
    )
    results_custom = await client_custom.search("test", count=3)
    assert results_custom[0].source_quality == "official"  # custom-official.com in custom official
    assert results_custom[1].source_quality == "high_quality"  # custom-hq.com in custom HQ
    assert results_custom[2].source_quality == "media"  # sec.gov not in custom lists


@pytest.mark.asyncio
async def test_run_investigations_concurrently_executes_multiple_runs(monkeypatch) -> None:
    rows = [
        AgentInvestigation(
            id="inv_1",
            target_type="event_cluster",
            target_id="evt_1",
            trigger_reason="auto_event_uncertain",
            status="pending",
            input_snapshot={"headline": "Oil jumps"},
            evidence=[],
        ),
        AgentInvestigation(
            id="inv_2",
            target_type="event_cluster",
            target_id="evt_2",
            trigger_reason="auto_event_uncertain",
            status="pending",
            input_snapshot={"headline": "Gold rises"},
            evidence=[],
        ),
    ]
    session = PendingSession(rows)

    class FakeProvider:
        async def investigate_event(self, prompt: str):
            return (
                LLMInvestigationResult(
                    summary="Checked.",
                    confidence=70,
                    official_confirmation="unconfirmed",
                    risk_flags=[],
                    suggested_score_modifier=2,
                    suggested_alert_level="daily_digest",
                    caveats=[],
                ),
                {"total_tokens": 15},
            )

    async def fake_gather(*args, **kwargs):
        return []

    monkeypatch.setattr(investigation_services, "llm_provider", lambda _config: FakeProvider())
    monkeypatch.setattr(investigation_services, "gather_investigation_evidence", fake_gather)

    result = await investigation_services.run_investigations_concurrently(
        session,
        rows,
        config=InvestigationConfig(enabled=True),
        llm_config=LLMConfig(enabled=True, api_key="llm-key"),
    )

    assert result == {"completed": 2, "failed": 0}
    assert rows[0].status == "succeeded"
    assert rows[1].status == "succeeded"
    assert rows[0].result["suggested_score_modifier"] == 2


