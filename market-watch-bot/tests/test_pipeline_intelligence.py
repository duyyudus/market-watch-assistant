from __future__ import annotations

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
from bot_worker.services.market import fetch_market_moves_with_stats
from bot_worker.services.pipeline import run_pipeline
from bot_worker.services.pipeline_metrics import PipelineRunMetrics, slow_pipeline_stages
from bot_worker.services.sources import (
    SourcePollingDecision,
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


def test_validate_pgvector_rejects_invalid_arrays_before_sql_execution() -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        validate_pgvector([], dimensions=3)
    with pytest.raises(ValueError, match="dimensions mismatch"):
        validate_pgvector([0.1, 0.2], dimensions=3)
    with pytest.raises(ValueError, match="must be numeric"):
        validate_pgvector([0.1, "bad", 0.3], dimensions=3)  # type: ignore[list-item]
