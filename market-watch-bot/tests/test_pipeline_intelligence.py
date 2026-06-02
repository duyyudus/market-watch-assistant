from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from bot_worker.db.models import DigestRecord, EventCluster, NewsSource, NormalizedNewsItem
from bot_worker.scoring import ScoreInput, score_event
from bot_worker.services.digests import format_digest_message
from bot_worker.services.events import validate_pgvector
from bot_worker.services.external_providers import (
    ProviderRetryPolicy,
    RateLimitCooldown,
    request_with_retry,
)
from bot_worker.services.full_text import (
    build_full_text_priority_stmt,
    extract_full_text_for_priority_events,
)
from bot_worker.services.market import fetch_market_moves_with_stats
from bot_worker.services.pipeline import run_pipeline
from bot_worker.services.pipeline_metrics import PipelineRunMetrics, slow_pipeline_stages
from bot_worker.services.sources import (
    SourcePollingDecision,
    compute_source_quality,
    effective_source_score,
    fetch_source,
    mark_source_fetch_result,
    should_poll_source,
)


class SequencedClient:
    def __init__(self, responses: list[httpx.Response | Exception]) -> None:
        self.responses = responses
        self.calls = 0

    async def request(self, method: str, url: str, **kwargs: object) -> httpx.Response:
        self.calls += 1
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        response.request = httpx.Request(method, url)
        return response


class EmptyScalarResult:
    def all(self) -> list[object]:
        return []


class EmptyPipelineSession:
    async def scalars(self, _stmt):
        return EmptyScalarResult()


class ListPipelineSession:
    def __init__(self, values: list[object]) -> None:
        self.values = values

    async def scalars(self, _stmt):
        return ListScalarResult(self.values)


class ListScalarResult:
    def __init__(self, values: list[object]) -> None:
        self.values = values

    def all(self) -> list[object]:
        return self.values


class FullTextSession:
    def __init__(self, items: list[NormalizedNewsItem], sources: dict[str, NewsSource]) -> None:
        self.items = items
        self.sources = sources
        self.get_calls = 0
        self.source_scalar_calls = 0

    async def scalars(self, _stmt):
        entity = _stmt.column_descriptions[0].get("entity")
        if entity is NewsSource:
            self.source_scalar_calls += 1
            return ListScalarResult(list(self.sources.values()))
        return ListScalarResult(self.items)

    async def get(self, _model, key: str):
        self.get_calls += 1
        raise AssertionError(f"full-text extraction must not call session.get({key!r})")


class FullTextClient:
    def __init__(self, responses: list[httpx.Response | Exception]) -> None:
        self.responses = responses
        self.active = 0
        self.max_active = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def get(self, url: str) -> httpx.Response:
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        await asyncio.sleep(0)
        response = self.responses.pop(0)
        self.active -= 1
        if isinstance(response, Exception):
            raise response
        response.request = httpx.Request("GET", url)
        return response


def full_text_item(
    *,
    item_id: str = "news_1",
    source_id: str = "src_1",
    snippet: str | None = "RSS summary",
    raw_content: str | None = None,
) -> NormalizedNewsItem:
    return NormalizedNewsItem(
        id=item_id,
        source_id=source_id,
        title="Market story",
        snippet=snippet,
        raw_content=raw_content,
        url="https://example.com/story",
        source_name="Example",
        source_type="rss",
        source_score=70,
        language="en",
        region="global",
        asset_classes=["global_macro"],
        is_paywalled=False,
        full_text_available=False,
        full_text_extraction_status="pending",
        title_hash="title",
        normalized_text_hash="body",
    )


def full_text_source(source_id: str = "src_1") -> NewsSource:
    return NewsSource(
        id=source_id,
        name="Example",
        source_type="rss",
        category="global_macro",
        region="global",
        asset_classes=["global_macro"],
        url="https://example.com/rss",
        source_score=70,
    )


@pytest.mark.asyncio
async def test_provider_retry_uses_retry_after_for_429_and_records_cooldown() -> None:
    sleeps: list[float] = []
    cooldowns: list[RateLimitCooldown] = []
    client = SequencedClient(
        [
            httpx.Response(429, headers={"Retry-After": "17"}, json={"error": "slow down"}),
            httpx.Response(200, json={"ok": True}),
        ]
    )

    response = await request_with_retry(
        provider="coingecko",
        method="GET",
        url="https://api.coingecko.com/api/v3/ping",
        retry_policy=ProviderRetryPolicy(max_retries=2, delays=(5, 15)),
        client=client,
        sleeper=sleeps.append,
        record_cooldown=cooldowns.append,
    )

    assert response.status_code == 200
    assert client.calls == 2
    assert sleeps == [17]
    assert cooldowns[0].provider == "coingecko"
    assert cooldowns[0].cooldown_seconds == 17
    assert cooldowns[0].http_status == 429


@pytest.mark.asyncio
async def test_provider_retry_returns_304_without_raising_status_error() -> None:
    client = SequencedClient([httpx.Response(304)])
    response = await request_with_retry(
        provider="rss",
        method="GET",
        url="https://example.com/rss",
        retry_policy=ProviderRetryPolicy(max_retries=1, delays=(1,)),
        client=client,
    )
    assert response.status_code == 304
    assert client.calls == 1


def test_score_event_uses_actual_watchlist_tier_and_high_quality_confirmation() -> None:
    d_tier = score_event(
        ScoreInput(
            top_source_score=78,
            source_count=2,
            watchlist_tier="D",
            is_duplicate=False,
            is_stale=False,
            unique_high_quality_source_count=0,
        )
    )
    s_tier_confirmed = score_event(
        ScoreInput(
            top_source_score=78,
            source_count=2,
            watchlist_tier="S",
            is_duplicate=False,
            is_stale=False,
            unique_high_quality_source_count=2,
        )
    )

    assert d_tier.relevance_score == 35
    assert s_tier_confirmed.relevance_score == 100
    assert s_tier_confirmed.confidence_score > d_tier.confidence_score
    assert s_tier_confirmed.final_score > d_tier.final_score


def test_source_polling_skips_interval_enters_burst_and_failure_cooldown() -> None:
    now = datetime(2026, 5, 31, 1, 0, tzinfo=UTC)
    source = NewsSource(
        id="src_1",
        name="Feed",
        source_type="rss",
        category="global_macro",
        region="global",
        asset_classes=["global_macro"],
        url="https://example.com/rss",
        polling_interval_seconds=900,
        last_fetched_at=now - timedelta(minutes=5),
    )

    assert should_poll_source(source, now=now) == SourcePollingDecision(
        should_poll=False,
        reason="interval_not_elapsed",
    )

    mark_source_fetch_result(source, now=now, status="success", inserted=3)
    assert source.burst_until_at == now + timedelta(minutes=30)
    assert source.consecutive_failure_count == 0
    assert should_poll_source(source, now=now + timedelta(minutes=3)).should_poll

    for offset in range(3):
        mark_source_fetch_result(
            source,
            now=now + timedelta(minutes=offset),
            status="failed",
            inserted=0,
        )
    assert source.consecutive_failure_count == 3
    assert source.disabled_until_at == now + timedelta(minutes=32)
    assert should_poll_source(source, now=now + timedelta(minutes=10)).reason == "failure_cooldown"


def test_effective_source_score_blends_manual_and_auto_quality() -> None:
    source = NewsSource(
        source_score=80,
        auto_quality_score=50,
    )

    assert effective_source_score(source) == 71


@pytest.mark.asyncio
async def test_compute_source_quality_uses_30_day_operational_signals() -> None:
    source = NewsSource(id="src_1", source_score=80)

    class QualitySession:
        async def scalar(self, stmt):
            text = str(stmt)
            if "source_fetch_logs" in text and "status = :status_1" in text:
                return 8
            if "source_fetch_logs" in text:
                return 10
            if (
                "normalized_news_items" in text
                and "processing_status = :processing_status_1" in text
            ):
                return 2
            if "event_cluster_items" in text:
                return 6
            if "normalized_news_items" in text:
                return 10
            return None

    score, metrics = await compute_source_quality(QualitySession(), source)

    assert score == 74
    assert metrics == {
        "reliability": 80,
        "duplicate_rate": 20,
        "event_contribution": 60,
    }


@pytest.mark.asyncio
async def test_fetch_source_skips_unsupported_existing_source_type(monkeypatch) -> None:
    source = NewsSource(
        id="src_unsupported",
        name="Unsupported",
        source_type="api",
        category="global_macro",
        region="global",
        asset_classes=["global_macro"],
        url="https://example.com/api",
        consecutive_failure_count=0,
    )

    async def fail_fetch_source_content(_source):
        raise AssertionError("unsupported source types should not be fetched")

    class FetchSession:
        def __init__(self) -> None:
            self.added: list[object] = []

        def add(self, value: object) -> None:
            self.added.append(value)

    monkeypatch.setattr(
        "bot_worker.services.sources.fetch_source_content",
        fail_fetch_source_content,
    )
    session = FetchSession()

    result = await fetch_source(session, source)

    assert result == {"status": "skipped", "reason": "unsupported_source_type"}
    assert source.consecutive_failure_count == 0
    assert session.added[0].status == "skipped"
    assert "Unsupported source_type: api" in session.added[0].error_message


@pytest.mark.asyncio
async def test_fetch_source_uses_conditional_headers_and_handles_not_modified(monkeypatch) -> None:
    source = NewsSource(
        id="src_1",
        name="Feed",
        source_type="rss",
        category="global_macro",
        region="global",
        asset_classes=["global_macro"],
        url="https://example.com/rss",
        etag='"abc"',
        last_modified="Mon, 01 Jun 2026 00:00:00 GMT",
    )
    calls: list[dict[str, object]] = []

    async def fake_fetch_source_content(source_arg):
        calls.append(
            {
                "etag": source_arg.etag,
                "last_modified": source_arg.last_modified,
            }
        )
        return 304, "", {}

    class FetchSession:
        def __init__(self) -> None:
            self.added: list[object] = []

        def add(self, value: object) -> None:
            self.added.append(value)

    monkeypatch.setattr(
        "bot_worker.services.sources.fetch_source_content",
        fake_fetch_source_content,
    )
    session = FetchSession()

    result = await fetch_source(session, source)

    assert result == {"status": "not_modified", "items": 0, "inserted": 0}
    assert calls == [{"etag": '"abc"', "last_modified": "Mon, 01 Jun 2026 00:00:00 GMT"}]
    assert source.last_fetched_at is not None
    assert session.added[0].status == "success"
    assert session.added[0].http_status == 304


def test_format_digest_message_groups_events_and_persists_digest_shape() -> None:
    since = datetime(2026, 5, 30, 1, 0, tzinfo=UTC)
    until = datetime(2026, 5, 31, 1, 0, tzinfo=UTC)
    events = [
        EventCluster(
            id="evt_1",
            canonical_headline="Fed signals rates can stay higher for longer",
            regions=["us"],
            asset_classes=["macro"],
            source_count=2,
            final_score=72,
            status="reported",
        ),
        EventCluster(
            id="evt_2",
            canonical_headline="Bitcoin rises after ETF inflow rebound",
            regions=["crypto"],
            asset_classes=["crypto"],
            source_count=3,
            final_score=68,
            status="confirmed",
        ),
    ]

    message = format_digest_message(events, since=since, until=until)
    digest = DigestRecord(
        digest_type="daily",
        window_start=since,
        window_end=until,
        content=message,
        status="built",
        event_count=len(events),
    )

    assert "[Daily Market Digest]" in message
    assert "US / macro" in message
    assert "CRYPTO / crypto" in message
    assert "Fed signals rates" in digest.content
    assert digest.event_count == 2


@pytest.mark.asyncio
async def test_market_fetch_continues_after_symbol_provider_failures() -> None:
    class MarketClient:
        async def get(self, url: str, **kwargs: object) -> httpx.Response:
            if "binance" in url:
                raise ValueError("bad json")
            if "coingecko" in url:
                response = httpx.Response(
                    200,
                    json=[{"id": "bitcoin", "price_change_percentage_24h": 4.2}],
                )
            else:
                response = httpx.Response(500, json={"error": "unexpected"})
            response.request = httpx.Request("GET", url)
            return response

        async def post(self, url: str, **kwargs: object) -> httpx.Response:
            response = httpx.Response(500, json={"error": "down"})
            response.request = httpx.Request("POST", url)
            return response

    result = await fetch_market_moves_with_stats(
        symbols=["BTC", "VIC"],
        window="1d",
        vn_base_url="https://vn.example",
        symbol_map={"BTC": "bitcoin"},
        client=MarketClient(),
    )

    assert [move.asset_symbol for move in result.moves] == ["BTC"]
    assert "binance" in result.degraded_providers
    assert "vietnam_market" in result.failed_providers


@pytest.mark.asyncio
async def test_market_fetch_uses_configured_crypto_provider_order() -> None:
    class MarketClient:
        def __init__(self) -> None:
            self.urls: list[str] = []

        async def get(self, url: str, **kwargs: object) -> httpx.Response:
            self.urls.append(url)
            if "binance" in url:
                raise AssertionError("Binance should not be called when CoinGecko succeeds")
            response = httpx.Response(
                200,
                json=[{"id": "bitcoin", "price_change_percentage_24h": 4.2}],
            )
            response.request = httpx.Request("GET", url)
            return response

    client = MarketClient()
    result = await fetch_market_moves_with_stats(
        symbols=["BTC"],
        window="1d",
        vn_base_url="https://vn.example",
        symbol_map={"BTC": "bitcoin"},
        crypto_provider="coingecko",
        crypto_fallback_provider="binance",
        client=client,
    )

    assert [move.asset_symbol for move in result.moves] == ["BTC"]
    assert len(client.urls) == 1
    assert "coingecko" in client.urls[0]


def test_normalized_news_item_supports_raw_content_for_full_text_extraction() -> None:
    item = NormalizedNewsItem(
        id="news_1",
        source_id="src_1",
        title="VN stocks rise",
        snippet="VN-Index gains",
        url="https://example.com/vn",
        source_name="Example",
        source_type="rss",
        source_score=60,
        language="vi",
        region="vn",
        asset_classes=["equity"],
        is_paywalled=False,
        full_text_available=True,
        title_hash="title",
        normalized_text_hash="body",
        raw_content="VN-Index tăng nhờ nhóm ngân hàng.",
    )

    assert item.raw_content.startswith("VN-Index")


def test_full_text_priority_query_tightens_single_source_and_stale_backlog() -> None:
    stmt = build_full_text_priority_stmt(
        threshold=70,
        single_source_threshold=80,
        lookback_days=7,
        limit=20,
    )
    text = str(stmt)

    assert "event_clusters.source_count > :source_count_1" in text
    assert "event_clusters.final_score >= :final_score_1" in text
    assert "event_clusters.source_count <= :source_count_2" in text
    assert "event_clusters.final_score >= :final_score_2" in text
    assert "normalized_news_items.created_at >= :created_at_1" in text


@pytest.mark.asyncio
async def test_full_text_terminal_http_error_uses_snippet_fallback(monkeypatch) -> None:
    item = full_text_item(snippet="Feed summary is usable.")
    source = full_text_source()
    session = FullTextSession([item], {source.id: source})

    monkeypatch.setattr(
        "bot_worker.services.full_text.httpx.AsyncClient",
        lambda **_kwargs: FullTextClient([httpx.Response(401, text="blocked")]),
    )

    stats = await extract_full_text_for_priority_events(session)

    assert stats.attempted == 1
    assert stats.extracted == 0
    assert stats.fallback_used == 1
    assert stats.skipped == 0
    assert stats.retryable_failed == 0
    assert stats.failed == 0
    assert item.raw_content == "Feed summary is usable."
    assert item.full_text_available is True
    assert item.full_text_extraction_status == "fallback"
    assert item.full_text_last_http_status == 401
    assert source.quality_metrics["full_text"]["fallback_used"] == 1


@pytest.mark.asyncio
async def test_full_text_extracts_limited_items_per_source_concurrently(monkeypatch) -> None:
    items = [
        full_text_item(item_id="news_1", source_id="src_1"),
        full_text_item(item_id="news_2", source_id="src_1"),
        full_text_item(item_id="news_3", source_id="src_1"),
        full_text_item(item_id="news_4", source_id="src_2"),
        full_text_item(item_id="news_5", source_id="src_2"),
    ]
    sources = {"src_1": full_text_source("src_1"), "src_2": full_text_source("src_2")}
    session = FullTextSession(items, sources)
    client = FullTextClient(
        [
            httpx.Response(200, text="<html><body>one</body></html>"),
            httpx.Response(200, text="<html><body>two</body></html>"),
            httpx.Response(200, text="<html><body>three</body></html>"),
            httpx.Response(200, text="<html><body>four</body></html>"),
        ]
    )

    monkeypatch.setattr(
        "bot_worker.services.full_text.httpx.AsyncClient",
        lambda **_kwargs: client,
    )

    stats = await extract_full_text_for_priority_events(session, per_source_limit=2)

    assert stats.attempted == 4
    assert stats.extracted == 4
    assert client.max_active == 4
    assert items[0].full_text_extraction_status == "extracted"
    assert items[1].full_text_extraction_status == "extracted"
    assert items[2].full_text_extraction_status == "pending"
    assert items[3].full_text_extraction_status == "extracted"
    assert items[4].full_text_extraction_status == "extracted"


@pytest.mark.asyncio
async def test_full_text_preloads_sources_without_concurrent_session_get(monkeypatch) -> None:
    items = [
        full_text_item(item_id="news_1", source_id="src_1"),
        full_text_item(item_id="news_2", source_id="src_2"),
    ]
    sources = {"src_1": full_text_source("src_1"), "src_2": full_text_source("src_2")}
    session = FullTextSession(items, sources)
    client = FullTextClient(
        [
            httpx.Response(200, text="<html><body>one</body></html>"),
            httpx.Response(200, text="<html><body>two</body></html>"),
        ]
    )

    monkeypatch.setattr(
        "bot_worker.services.full_text.httpx.AsyncClient",
        lambda **_kwargs: client,
    )

    stats = await extract_full_text_for_priority_events(session)

    assert stats.attempted == 2
    assert stats.extracted == 2
    assert client.max_active == 2
    assert session.get_calls == 0
    assert session.source_scalar_calls == 1
    assert sources["src_1"].quality_metrics["full_text"]["extracted"] == 1
    assert sources["src_2"].quality_metrics["full_text"]["extracted"] == 1


@pytest.mark.asyncio
async def test_full_text_terminal_http_error_without_fallback_is_skipped(monkeypatch) -> None:
    item = full_text_item(snippet=None, raw_content=None)
    source = full_text_source()
    session = FullTextSession([item], {source.id: source})

    monkeypatch.setattr(
        "bot_worker.services.full_text.httpx.AsyncClient",
        lambda **_kwargs: FullTextClient([httpx.Response(403, text="blocked")]),
    )

    stats = await extract_full_text_for_priority_events(session)

    assert stats.skipped == 1
    assert stats.failed == 0
    assert item.full_text_available is False
    assert item.full_text_extraction_status == "skipped"
    assert item.full_text_last_http_status == 403


@pytest.mark.asyncio
async def test_full_text_retryable_http_error_marks_retry(monkeypatch) -> None:
    item = full_text_item()
    source = full_text_source()
    session = FullTextSession([item], {source.id: source})

    monkeypatch.setattr(
        "bot_worker.services.full_text.httpx.AsyncClient",
        lambda **_kwargs: FullTextClient([httpx.Response(503, text="unavailable")]),
    )

    stats = await extract_full_text_for_priority_events(session)

    assert stats.retryable_failed == 1
    assert stats.failed == 1
    assert item.full_text_available is False
    assert item.full_text_extraction_status == "retry"
    assert item.full_text_next_retry_at is not None


@pytest.mark.asyncio
async def test_full_text_success_sets_extracted_status(monkeypatch) -> None:
    item = full_text_item()
    source = full_text_source()
    session = FullTextSession([item], {source.id: source})
    html = (
        "<html><body><article><p>Market text with enough useful detail.</p></article></body>"
        "</html>"
    )

    monkeypatch.setattr(
        "bot_worker.services.full_text.httpx.AsyncClient",
        lambda **_kwargs: FullTextClient([httpx.Response(200, text=html)]),
    )

    stats = await extract_full_text_for_priority_events(session)

    assert stats.extracted == 1
    assert stats.failed == 0
    assert item.full_text_available is True
    assert item.full_text_extraction_status == "extracted"
    assert "Market text" in item.raw_content


def test_pipeline_metrics_detects_stages_slower_than_prior_average() -> None:
    current = PipelineRunMetrics()
    current.record_stage(
        stage_name="poll_sources",
        start_time=datetime(2026, 6, 1, 1, 0, tzinfo=UTC),
        end_time=datetime(2026, 6, 1, 1, 0, 3, tzinfo=UTC),
        items_in=10,
        items_out=8,
        status="success",
    )
    prior_results = [
        {
            "pipeline_metrics": {
                "stages": [
                    {"stage_name": "poll_sources", "duration_ms": 1000},
                    {"stage_name": "poll_sources", "duration_ms": 1200},
                ]
            }
        }
    ]

    slow = slow_pipeline_stages(current.to_dict(), prior_results)

    assert slow == [
        {
            "stage_name": "poll_sources",
            "duration_ms": 3000,
            "average_duration_ms": 1100,
            "threshold_ms": 2200,
        }
    ]


@pytest.mark.asyncio
async def test_run_pipeline_persists_stage_metrics_in_result(monkeypatch) -> None:
    async def return_zero(*_args, **_kwargs):
        return 0

    async def return_empty_list(*_args, **_kwargs):
        return []

    async def return_cluster_stats(*_args, **_kwargs):
        from bot_worker.services.events import ClusterBuildStats

        return ClusterBuildStats()

    async def return_full_text_stats(*_args, **_kwargs):
        return type("FullTextStats", (), {"extracted": 0, "failed": 0})()

    monkeypatch.setattr("bot_worker.services.pipeline.normalize_pending_raw_items", return_zero)
    monkeypatch.setattr("bot_worker.services.pipeline.mark_exact_duplicates", return_zero)
    monkeypatch.setattr("bot_worker.services.pipeline.build_event_clusters", return_cluster_stats)
    monkeypatch.setattr(
        "bot_worker.services.pipeline.extract_full_text_for_priority_events",
        return_full_text_stats,
    )
    monkeypatch.setattr("bot_worker.services.pipeline.record_alert_decisions", return_zero)
    monkeypatch.setattr("bot_worker.services.pipeline.run_missed_catalyst_review", return_zero)
    monkeypatch.setattr("bot_worker.services.pipeline.watchlist_entries", return_empty_list)

    result = await run_pipeline(EmptyPipelineSession())

    assert "pipeline_metrics" in result
    metrics = result["pipeline_metrics"]
    assert metrics["status"] == "success"
    assert [stage["stage_name"] for stage in metrics["stages"]] == [
        "poll_sources",
        "normalize_raw_items",
        "dedupe_news_items",
        "extract_entities",
        "generate_embeddings",
        "cluster_events",
        "generate_event_embeddings",
        "enrich_events_with_llm",
        "fetch_market_moves",
        "full_text_extraction",
        "record_alert_decisions",
        "run_missed_catalyst_review",
    ]
    assert all("duration_ms" in stage for stage in metrics["stages"])


@pytest.mark.asyncio
async def test_run_pipeline_keeps_full_text_stage_success_for_terminal_fallbacks(
    monkeypatch,
) -> None:
    async def return_zero(*_args, **_kwargs):
        return 0

    async def return_empty_list(*_args, **_kwargs):
        return []

    async def return_cluster_stats(*_args, **_kwargs):
        from bot_worker.services.events import ClusterBuildStats

        return ClusterBuildStats()

    async def return_full_text_stats(*_args, **_kwargs):
        return type(
            "FullTextStats",
            (),
            {
                "attempted": 20,
                "extracted": 16,
                "fallback_used": 4,
                "skipped": 0,
                "retryable_failed": 0,
                "failed": 0,
            },
        )()

    monkeypatch.setattr("bot_worker.services.pipeline.normalize_pending_raw_items", return_zero)
    monkeypatch.setattr("bot_worker.services.pipeline.mark_exact_duplicates", return_zero)
    monkeypatch.setattr("bot_worker.services.pipeline.build_event_clusters", return_cluster_stats)
    monkeypatch.setattr(
        "bot_worker.services.pipeline.extract_full_text_for_priority_events",
        return_full_text_stats,
    )
    monkeypatch.setattr("bot_worker.services.pipeline.record_alert_decisions", return_zero)
    monkeypatch.setattr("bot_worker.services.pipeline.run_missed_catalyst_review", return_zero)
    monkeypatch.setattr("bot_worker.services.pipeline.watchlist_entries", return_empty_list)

    result = await run_pipeline(EmptyPipelineSession())

    assert result["full_text_attempted"] == 20
    assert result["full_text_extracted"] == 16
    assert result["full_text_fallback_used"] == 4
    assert result["full_text_skipped"] == 0
    assert result["full_text_retryable_failed"] == 0
    assert "full_text_extraction" not in result["degraded_stages"]
    stage = next(
        stage
        for stage in result["pipeline_metrics"]["stages"]
        if stage["stage_name"] == "full_text_extraction"
    )
    assert stage["status"] == "success"


@pytest.mark.asyncio
async def test_run_pipeline_keeps_poll_sources_success_for_interval_skips(monkeypatch) -> None:
    source = NewsSource(
        id="src_1",
        name="Recently fetched",
        source_type="rss",
        category="global_macro",
        region="global",
        asset_classes=["global_macro"],
        url="https://example.com/rss",
    )

    async def skip_interval(*_args, **_kwargs):
        return {"status": "skipped", "reason": "interval_not_elapsed"}

    async def return_zero(*_args, **_kwargs):
        return 0

    async def return_empty_list(*_args, **_kwargs):
        return []

    async def return_cluster_stats(*_args, **_kwargs):
        from bot_worker.services.events import ClusterBuildStats

        return ClusterBuildStats()

    async def return_full_text_stats(*_args, **_kwargs):
        return type(
            "FullTextStats",
            (),
            {
                "attempted": 0,
                "extracted": 0,
                "fallback_used": 0,
                "skipped": 0,
                "retryable_failed": 0,
                "failed": 0,
            },
        )()

    monkeypatch.setattr("bot_worker.services.pipeline.fetch_source", skip_interval)
    monkeypatch.setattr("bot_worker.services.pipeline.normalize_pending_raw_items", return_zero)
    monkeypatch.setattr("bot_worker.services.pipeline.mark_exact_duplicates", return_zero)
    monkeypatch.setattr("bot_worker.services.pipeline.build_event_clusters", return_cluster_stats)
    monkeypatch.setattr(
        "bot_worker.services.pipeline.extract_full_text_for_priority_events",
        return_full_text_stats,
    )
    monkeypatch.setattr("bot_worker.services.pipeline.record_alert_decisions", return_zero)
    monkeypatch.setattr("bot_worker.services.pipeline.run_missed_catalyst_review", return_zero)
    monkeypatch.setattr("bot_worker.services.pipeline.watchlist_entries", return_empty_list)

    result = await run_pipeline(ListPipelineSession([source]))

    assert result["skipped_sources"] == 1
    assert result["poll_source_cooldown_skips"] == 0
    assert "poll_sources" not in result["degraded_stages"]
    stage = next(
        stage
        for stage in result["pipeline_metrics"]["stages"]
        if stage["stage_name"] == "poll_sources"
    )
    assert stage["status"] == "success"


def test_validate_pgvector_rejects_invalid_arrays_before_sql_execution() -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        validate_pgvector([], dimensions=3)
    with pytest.raises(ValueError, match="dimensions mismatch"):
        validate_pgvector([0.1, 0.2], dimensions=3)
    with pytest.raises(ValueError, match="must be numeric"):
        validate_pgvector([0.1, "bad", 0.3], dimensions=3)  # type: ignore[list-item]
