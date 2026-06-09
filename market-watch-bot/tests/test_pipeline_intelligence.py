from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from bot_worker.db.models import DigestRecord, EventCluster, NewsSource, NormalizedNewsItem
from bot_worker.embeddings import EmbeddingConfig
from bot_worker.llm import LLMConfig
from bot_worker.scoring import ScoreInput, score_event
from bot_worker.services.digests import format_digest_message
from bot_worker.services.events import validate_pgvector
from bot_worker.services.external_providers import (
    ProviderRetryPolicy,
    RateLimitCooldown,
    request_with_retry,
)
from bot_worker.services.full_text import (
    build_full_text_backlog_stmt,
    extract_full_text_for_pending_items,
)
from bot_worker.services.market import fetch_market_moves_with_stats
from bot_worker.services.pipeline import run_pipeline
from bot_worker.services.pipeline_metrics import PipelineRunMetrics, slow_pipeline_stages
from bot_worker.services.sources import (
    SourcePollingDecision,
    compute_source_quality,
    effective_source_score,
    fetch_source,
    fetch_source_content,
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


class NestedPipelineSession(EmptyPipelineSession):
    def __init__(self) -> None:
        self.in_nested_transaction = False
        self.transaction_poisoned = False
        self.nested_transactions = 0

    def begin_nested(self):
        session = self

        class NestedTransaction:
            async def __aenter__(self):
                session.nested_transactions += 1
                session.in_nested_transaction = True
                return self

            async def __aexit__(self, *_args):
                session.in_nested_transaction = False
                return False

        return NestedTransaction()


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
        self.active_by_domain: dict[str, int] = {}
        self.max_active_by_domain: dict[str, int] = {}
        self.requests: list[tuple[str, dict[str, str]]] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def get(self, url: str, **kwargs: object) -> httpx.Response:
        from urllib.parse import urlsplit

        domain = urlsplit(url).netloc
        headers = kwargs.get("headers") or {}
        self.requests.append((url, dict(headers)))
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        self.active_by_domain[domain] = self.active_by_domain.get(domain, 0) + 1
        self.max_active_by_domain[domain] = max(
            self.max_active_by_domain.get(domain, 0),
            self.active_by_domain[domain],
        )
        await asyncio.sleep(0)
        response = self.responses.pop(0)
        self.active -= 1
        self.active_by_domain[domain] -= 1
        if isinstance(response, Exception):
            raise response
        response.request = httpx.Request("GET", url)
        return response


def full_text_item(
    *,
    item_id: str = "news_1",
    source_id: str = "src_1",
    title: str = "Market story",
    snippet: str | None = "RSS summary",
    raw_content: str | None = None,
    source_type: str = "rss",
    url: str = "https://example.com/story",
) -> NormalizedNewsItem:
    return NormalizedNewsItem(
        id=item_id,
        source_id=source_id,
        title=title,
        snippet=snippet,
        raw_content=raw_content,
        url=url,
        source_name="Example",
        source_type=source_type,
        source_score=70,
        language="en",
        region="global",
        asset_classes=["global_macro"],
        is_paywalled=False,
        full_text_available=False,
        full_text_extraction_status="pending",
        full_text_attempt_count=0,
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


@pytest.mark.asyncio
async def test_fetch_source_content_uses_normal_request(monkeypatch) -> None:
    requests: list[tuple[str, str, dict[str, object]]] = []

    class NormalClient:
        def __init__(self, **_kwargs: object) -> None:
            return None

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

        async def request(self, method: str, url: str, **kwargs: object) -> httpx.Response:
            requests.append((method, url, kwargs))
            response = httpx.Response(200, text="<rss></rss>")
            response.request = httpx.Request(method, url)
            return response

    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
    monkeypatch.setattr("bot_worker.services.sources.httpx.AsyncClient", NormalClient)
    source = NewsSource(
        id="src_normal",
        name="Normal - Stock News",
        source_type="rss",
        category="us_equity",
        region="us",
        asset_classes=["us_equity"],
        url="https://example.com/rss/news_25.rss",
    )

    status_code, body, _headers = await fetch_source_content(source)

    assert status_code == 200
    assert body == "<rss></rss>"
    assert requests == [
        (
            "GET",
            "https://example.com/rss/news_25.rss",
            {
                "headers": {
                    "User-Agent": "market-watch-assistant/0.1 (+https://github.com/market-watch-assistant)",
                }
            },
        )
    ]


@pytest.mark.asyncio
async def test_fetch_source_formats_transport_error_with_exception_type(monkeypatch) -> None:
    source = NewsSource(
        id="src_transport_error",
        name="Blocked Feed",
        source_type="rss",
        category="global_macro",
        region="global",
        asset_classes=["global_macro"],
        url="https://example.com/rss",
        consecutive_failure_count=0,
    )

    async def fail_fetch_source_content(_source):
        raise httpx.ConnectError("[Errno 104] Connection reset by peer")

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

    assert result == {
        "status": "failed",
        "error": "ConnectError: [Errno 104] Connection reset by peer",
    }
    assert session.added[0].error_message == "ConnectError: [Errno 104] Connection reset by peer"


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


@pytest.mark.asyncio
async def test_fetch_source_keeps_google_rss_item_url_before_insert(monkeypatch) -> None:
    source = NewsSource(
        id="src_google_rss",
        name="FT Google RSS",
        source_type="google-rss",
        category="global_macro",
        region="global",
        asset_classes=["global_macro"],
        url="https://news.google.com/rss/search?q=site:ft.com+markets",
    )
    google_url = "https://news.google.com/rss/articles/encoded?oc=5"
    rss_body = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <item>
      <title>Markets rally</title>
      <link>{google_url}</link>
      <description>Stocks rise.</description>
      <guid>item-1</guid>
    </item>
  </channel>
</rss>
"""

    async def fake_fetch_source_content(_source):
        return 200, rss_body, {}

    class FetchSession:
        def __init__(self) -> None:
            self.added: list[object] = []
            self.insert_values: list[dict[str, object]] = []

        def add(self, value: object) -> None:
            self.added.append(value)

        async def execute(self, stmt):
            self.insert_values.append(dict(stmt.compile().params))

            class Result:
                rowcount = 1

            return Result()

        async def scalars(self, stmt):
            class FakeResult:
                def all(self):
                    return []
            return FakeResult()

    monkeypatch.setattr(
        "bot_worker.services.sources.fetch_source_content",
        fake_fetch_source_content,
    )
    session = FetchSession()

    result = await fetch_source(session, source)

    assert result == {"status": "success", "items": 1, "inserted": 1}
    assert session.insert_values[0]["raw_url"] == google_url
    assert session.insert_values[0]["raw_description"] == ""
    assert session.insert_values[0]["raw_payload"]["google_news_url"] == google_url
    assert "google_news_decoded_url" not in session.insert_values[0]["raw_payload"]
    assert "google_news_decode_status" not in session.insert_values[0]["raw_payload"]


@pytest.mark.asyncio
async def test_fetch_source_google_rss_does_not_call_url_resolver(monkeypatch) -> None:
    source = NewsSource(
        id="src_google_rss",
        name="Reuters Google RSS",
        source_type="google-rss",
        category="global_macro",
        region="global",
        asset_classes=["global_macro"],
        url="https://news.google.com/rss/search?q=site:reuters.com+markets",
    )
    google_url = "https://news.google.com/rss/articles/encoded?oc=5"
    rss_body = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <item>
      <title>Oil slips</title>
      <link>{google_url}</link>
      <description>Crude prices fall.</description>
      <guid>item-1</guid>
    </item>
  </channel>
</rss>
"""

    async def fake_fetch_source_content(_source):
        return 200, rss_body, {}

    class FetchSession:
        def __init__(self) -> None:
            self.added: list[object] = []
            self.insert_values: list[dict[str, object]] = []

        def add(self, value: object) -> None:
            self.added.append(value)

        async def execute(self, stmt):
            self.insert_values.append(dict(stmt.compile().params))

            class Result:
                rowcount = 1

            return Result()

        async def scalars(self, stmt):
            class FakeResult:
                def all(self):
                    return []
            return FakeResult()

    monkeypatch.setattr(
        "bot_worker.services.sources.fetch_source_content",
        fake_fetch_source_content,
    )
    session = FetchSession()

    result = await fetch_source(session, source)

    assert result == {"status": "success", "items": 1, "inserted": 1}
    assert session.insert_values[0]["raw_url"] == google_url
    assert session.insert_values[0]["raw_payload"]["google_news_url"] == google_url
    assert "google_news_decode_status" not in session.insert_values[0]["raw_payload"]


@pytest.mark.asyncio
async def test_fetch_google_rss_content_uses_rss_retry_provider(monkeypatch) -> None:
    source = NewsSource(
        id="src_google_rss",
        name="FT Google RSS",
        source_type="google-rss",
        category="global_macro",
        region="global",
        asset_classes=["global_macro"],
        url="https://news.google.com/rss/search?q=site:ft.com+markets",
    )
    providers: list[str] = []

    async def fake_request_with_retry(**kwargs):
        providers.append(kwargs["provider"])
        response = httpx.Response(200, text="<rss></rss>")
        response.request = httpx.Request("GET", source.url)
        return response

    monkeypatch.setattr(
        "bot_worker.services.sources.request_with_retry",
        fake_request_with_retry,
    )

    status_code, body, _headers = await fetch_source_content(source)

    assert status_code == 200
    assert body == "<rss></rss>"
    assert providers == ["rss"]


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


def test_full_text_backlog_query_selects_pending_normalized_items_without_event_filter() -> None:
    stmt = build_full_text_backlog_stmt(limit=500)
    text = str(stmt)

    assert "JOIN event_cluster_items" not in text
    assert "JOIN event_clusters" not in text
    assert "normalized_news_items.processing_status = :processing_status_1" in text
    assert "normalized_news_items.source_type != :source_type_1" in text
    assert (
        "normalized_news_items.full_text_extraction_status = :full_text_extraction_status_1"
        in text
    )
    assert (
        "normalized_news_items.full_text_extraction_status = :full_text_extraction_status_2"
        in text
    )


@pytest.mark.asyncio
async def test_full_text_skips_google_rss_items_without_http(monkeypatch) -> None:
    item = full_text_item(source_type="google-rss")
    source = full_text_source()
    source.source_type = "google-rss"
    session = FullTextSession([item], {source.id: source})
    client = FullTextClient([httpx.Response(200, text="<html><body>unused</body></html>")])

    monkeypatch.setattr(
        "bot_worker.services.full_text.httpx.AsyncClient",
        lambda **_kwargs: client,
    )

    stats = await extract_full_text_for_pending_items(session)

    assert stats.attempted == 0
    assert stats.skipped == 1
    assert client.requests == []
    assert item.full_text_available is False
    assert item.full_text_extraction_status == "skipped"
    assert item.full_text_last_error == "google_rss_feed_only"


@pytest.mark.asyncio
async def test_full_text_terminal_http_error_uses_snippet_fallback(monkeypatch) -> None:
    item = full_text_item(snippet="Feed summary is usable.")
    source = full_text_source()
    session = FullTextSession([item], {source.id: source})

    monkeypatch.setattr(
        "bot_worker.services.full_text.httpx.AsyncClient",
        lambda **_kwargs: FullTextClient([httpx.Response(401, text="blocked")]),
    )

    stats = await extract_full_text_for_pending_items(session)

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
async def test_full_text_extracts_all_selected_items_concurrently(monkeypatch) -> None:
    items = [
        full_text_item(item_id="news_1", source_id="src_1", url="https://one.example/story"),
        full_text_item(item_id="news_2", source_id="src_1", url="https://two.example/story"),
        full_text_item(item_id="news_3", source_id="src_1", url="https://three.example/story"),
        full_text_item(item_id="news_4", source_id="src_2", url="https://four.example/story"),
        full_text_item(item_id="news_5", source_id="src_2", url="https://five.example/story"),
    ]
    sources = {"src_1": full_text_source("src_1"), "src_2": full_text_source("src_2")}
    session = FullTextSession(items, sources)
    client = FullTextClient(
        [
            httpx.Response(200, text="<html><body>one</body></html>"),
            httpx.Response(200, text="<html><body>two</body></html>"),
            httpx.Response(200, text="<html><body>three</body></html>"),
            httpx.Response(200, text="<html><body>four</body></html>"),
            httpx.Response(200, text="<html><body>five</body></html>"),
        ]
    )

    monkeypatch.setattr(
        "bot_worker.services.full_text.httpx.AsyncClient",
        lambda **_kwargs: client,
    )

    stats = await extract_full_text_for_pending_items(session)

    assert stats.attempted == 5
    assert stats.extracted == 5
    assert client.max_active == 5
    assert items[0].full_text_extraction_status == "extracted"
    assert items[1].full_text_extraction_status == "extracted"
    assert items[2].full_text_extraction_status == "extracted"
    assert items[3].full_text_extraction_status == "extracted"
    assert items[4].full_text_extraction_status == "extracted"


@pytest.mark.asyncio
async def test_full_text_serializes_requests_per_article_domain(monkeypatch) -> None:
    items = [
        full_text_item(item_id="news_1", url="https://vnexpress.net/story-1"),
        full_text_item(item_id="news_2", url="https://vnexpress.net/story-2"),
        full_text_item(item_id="news_3", url="https://vnexpress.net/story-3"),
    ]
    source = full_text_source()
    session = FullTextSession(items, {source.id: source})
    client = FullTextClient(
        [
            httpx.Response(200, text="<html><body>one</body></html>"),
            httpx.Response(200, text="<html><body>two</body></html>"),
            httpx.Response(200, text="<html><body>three</body></html>"),
        ]
    )

    monkeypatch.setattr(
        "bot_worker.services.full_text.httpx.AsyncClient",
        lambda **_kwargs: client,
    )

    stats = await extract_full_text_for_pending_items(session, max_concurrency=3)

    assert stats.extracted == 3
    assert client.max_active_by_domain["vnexpress.net"] == 1


@pytest.mark.asyncio
async def test_full_text_defers_same_domain_after_rate_limit(monkeypatch) -> None:
    items = [
        full_text_item(item_id="news_1", url="https://vnexpress.net/story-1"),
        full_text_item(item_id="news_2", url="https://vnexpress.net/story-2"),
    ]
    items[1].full_text_last_http_status = 429
    source = full_text_source()
    session = FullTextSession(items, {source.id: source})
    client = FullTextClient(
        [
            httpx.Response(429, headers={"Retry-After": "120"}, text="slow down"),
            httpx.Response(200, text="<html><body>should not be requested</body></html>"),
        ]
    )

    monkeypatch.setattr(
        "bot_worker.services.full_text.httpx.AsyncClient",
        lambda **_kwargs: client,
    )

    stats = await extract_full_text_for_pending_items(session, max_concurrency=2)

    assert stats.attempted == 1
    assert stats.retryable_failed == 2
    assert [request[0] for request in client.requests] == ["https://vnexpress.net/story-1"]
    assert items[0].full_text_extraction_status == "retry"
    assert items[0].full_text_last_error == "http_429"
    assert items[1].full_text_extraction_status == "retry"
    assert items[1].full_text_last_error == "source_rate_limited"
    assert items[1].full_text_last_http_status is None
    assert items[1].full_text_attempt_count == 0
    assert items[1].full_text_next_retry_at is not None


@pytest.mark.asyncio
async def test_full_text_spaces_requests_per_article_domain(monkeypatch) -> None:
    items = [
        full_text_item(item_id="news_1", url="https://vnexpress.net/story-1"),
        full_text_item(item_id="news_2", url="https://vnexpress.net/story-2"),
    ]
    source = full_text_source()
    session = FullTextSession(items, {source.id: source})
    client = FullTextClient(
        [
            httpx.Response(200, text="<html><body>one</body></html>"),
            httpx.Response(200, text="<html><body>two</body></html>"),
        ]
    )
    sleep_calls: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleep_calls.append(delay)

    monkeypatch.setattr(
        "bot_worker.services.full_text.httpx.AsyncClient",
        lambda **_kwargs: client,
    )
    monkeypatch.setattr("bot_worker.services.full_text.asyncio.sleep", fake_sleep)

    stats = await extract_full_text_for_pending_items(
        session,
        max_concurrency=2,
        domain_request_interval_seconds=1.5,
    )

    assert stats.extracted == 2
    assert any(delay >= 1.4 for delay in sleep_calls)


@pytest.mark.asyncio
async def test_full_text_preloads_sources_without_concurrent_session_get(monkeypatch) -> None:
    items = [
        full_text_item(item_id="news_1", source_id="src_1", url="https://one.example/story"),
        full_text_item(item_id="news_2", source_id="src_2", url="https://two.example/story"),
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

    stats = await extract_full_text_for_pending_items(session)

    assert stats.attempted == 2
    assert stats.extracted == 2
    assert client.max_active == 2
    assert session.get_calls == 0
    assert session.source_scalar_calls == 1
    assert sources["src_1"].quality_metrics["full_text"]["extracted"] == 1
    assert sources["src_2"].quality_metrics["full_text"]["extracted"] == 1


@pytest.mark.asyncio
async def test_full_text_terminal_http_error_without_fallback_is_skipped(monkeypatch) -> None:
    item = full_text_item(title="", snippet=None, raw_content=None)
    source = full_text_source()
    session = FullTextSession([item], {source.id: source})

    monkeypatch.setattr(
        "bot_worker.services.full_text.httpx.AsyncClient",
        lambda **_kwargs: FullTextClient([httpx.Response(403, text="blocked")]),
    )

    stats = await extract_full_text_for_pending_items(session)

    assert stats.skipped == 1
    assert stats.failed == 0
    assert item.full_text_available is False
    assert item.full_text_extraction_status == "skipped"
    assert item.full_text_last_http_status == 403


@pytest.mark.asyncio
async def test_full_text_terminal_http_error_uses_title_fallback(monkeypatch) -> None:
    item = full_text_item(
        title="Oil supply shock analysis",
        snippet=None,
        raw_content=None,
    )
    source = full_text_source()
    session = FullTextSession([item], {source.id: source})

    monkeypatch.setattr(
        "bot_worker.services.full_text.httpx.AsyncClient",
        lambda **_kwargs: FullTextClient([httpx.Response(403, text="blocked")]),
    )

    stats = await extract_full_text_for_pending_items(session)

    assert stats.attempted == 1
    assert stats.fallback_used == 1
    assert stats.skipped == 0
    assert item.raw_content == "Oil supply shock analysis"
    assert item.full_text_available is True
    assert item.full_text_extraction_status == "fallback"
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

    stats = await extract_full_text_for_pending_items(session)

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

    stats = await extract_full_text_for_pending_items(session)

    assert stats.extracted == 1
    assert stats.failed == 0
    assert item.full_text_available is True
    assert item.full_text_extraction_status == "extracted"
    assert "Market text" in item.raw_content


@pytest.mark.asyncio
async def test_full_text_fetch_uses_article_user_agent(monkeypatch) -> None:
    item = full_text_item()
    source = full_text_source()
    session = FullTextSession([item], {source.id: source})
    client = FullTextClient(
        [
            httpx.Response(
                200,
                text="<html><body><article>Market text with enough detail.</article></body></html>",
            )
        ]
    )

    monkeypatch.setattr(
        "bot_worker.services.full_text.httpx.AsyncClient",
        lambda **_kwargs: client,
    )

    stats = await extract_full_text_for_pending_items(session)

    assert stats.extracted == 1
    assert client.requests[0][1]["User-Agent"].startswith("market-watch-assistant/")


@pytest.mark.asyncio
async def test_full_text_success_uses_shared_boilerplate_cleanup(monkeypatch) -> None:
    item = full_text_item()
    source = full_text_source()
    session = FullTextSession([item], {source.id: source})
    html = """
    <html><body><article>
      <p>Market text with enough useful detail.</p>
      <div class="box-vif">
        <p>Diễn đàn Đầu tư Việt Nam 2026 - Summer Summit</p>
        <p>Vietnam Investment Forum 2026 - Summer Summit quy tụ chuyên gia.</p>
      </div>
    </article></body></html>
    """

    monkeypatch.setattr(
        "bot_worker.services.full_text.httpx.AsyncClient",
        lambda **_kwargs: FullTextClient([httpx.Response(200, text=html)]),
    )

    stats = await extract_full_text_for_pending_items(session)

    assert stats.extracted == 1
    assert item.raw_content is not None
    assert "Market text with enough useful detail" in item.raw_content
    assert "Vietnam Investment Forum 2026" not in item.raw_content


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
        "bot_worker.services.pipeline.extract_full_text_for_pending_items",
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
        "full_text_extraction",
        "extract_entities",
        "generate_embeddings",
        "cluster_events",
        "generate_event_embeddings",
        "enrich_events_with_llm",
        "fetch_market_moves",
        "record_alert_decisions",
        "run_missed_catalyst_review",
    ]
    assert all("duration_ms" in stage for stage in metrics["stages"])


@pytest.mark.asyncio
async def test_run_pipeline_isolates_entity_extraction_failure_from_later_stages(
    monkeypatch,
) -> None:
    session = NestedPipelineSession()

    async def fail_entity_extraction(active_session, *_args, **_kwargs):
        if not active_session.in_nested_transaction:
            active_session.transaction_poisoned = True
        raise ValueError("entity ticker too long")

    async def embed_news(active_session, *_args, **_kwargs):
        if active_session.transaction_poisoned:
            raise AssertionError("later stage saw poisoned transaction")
        return 3

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
    monkeypatch.setattr(
        "bot_worker.services.pipeline.extract_entities_with_llm",
        fail_entity_extraction,
    )
    monkeypatch.setattr("bot_worker.services.pipeline.embed_pending_news_items", embed_news)
    monkeypatch.setattr("bot_worker.services.pipeline.build_event_clusters", return_cluster_stats)
    monkeypatch.setattr("bot_worker.services.pipeline.embed_pending_event_clusters", return_zero)
    monkeypatch.setattr("bot_worker.services.pipeline.enrich_event_clusters_with_llm", return_zero)
    monkeypatch.setattr(
        "bot_worker.services.pipeline.extract_full_text_for_pending_items",
        return_full_text_stats,
    )
    monkeypatch.setattr("bot_worker.services.pipeline.record_alert_decisions", return_zero)
    monkeypatch.setattr("bot_worker.services.pipeline.run_missed_catalyst_review", return_zero)
    monkeypatch.setattr("bot_worker.services.pipeline.watchlist_entries", return_empty_list)

    result = await run_pipeline(
        session,
        embedding_config=EmbeddingConfig(provider="local"),
        llm_config=LLMConfig(enabled=True, api_key="key"),
    )

    assert result["news_embeddings"] == 3
    assert result["degraded_stages"] == ["extract_entities"]
    assert "generate_embeddings" not in result["degraded_stages"]
    assert session.nested_transactions > 0


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
        "bot_worker.services.pipeline.extract_full_text_for_pending_items",
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
        "bot_worker.services.pipeline.extract_full_text_for_pending_items",
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
