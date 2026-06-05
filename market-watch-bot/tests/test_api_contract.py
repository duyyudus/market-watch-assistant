from __future__ import annotations

from datetime import UTC, datetime

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from api_server.app.db import Base, get_session
from api_server.app.main import app
from common.config import Settings
from common.db.models import (
    AgentInvestigation,
    AlertChannel,
    AlertSuppressionRule,
    AppSetting,
    BotCommand,
    EventCluster,
    EventClusterEmbedding,
    EventClusterItem,
    EventScoreHistory,
    JobRun,
    LLMAnalysisRun,
    MarketMove,
    MissedCatalystReview,
    NewsItemEmbedding,
    NewsSource,
    NormalizedNewsItem,
    RetentionJob,
    SourceFetchLog,
    WatchlistEntity,
)
from common.db.models import (
    AlertDecisionRecord as AlertDecision,
)
from common.source_preview import ArticlePreviewResult, SourcePreviewResult

AUTH_HEADERS = {"Authorization": "Bearer test-token"}


@pytest.fixture()
async def client():
    app.state.settings = Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        api_auth_token="test-token",
    )
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        source = NewsSource(
            id="src_1",
            name="Federal Reserve",
            source_type="official",
            category="global_macro",
            region="us",
            asset_classes=["global_macro"],
            url="https://example.com/rss",
            language="en",
            enabled=True,
            polling_interval_seconds=900,
            source_score=100,
        )
        event = EventCluster(
            id="evt_1",
            canonical_headline="Fed signals a slower rate path",
            summary="Policy makers leaned less hawkish.",
            status="reported",
            regions=["us"],
            asset_classes=["global_macro"],
            affected_entities=["Federal Reserve"],
            affected_tickers=["SPY"],
            source_count=2,
            top_source_score=100,
            confirmation_score=88,
            novelty_score=85,
            urgency_score=80,
            market_impact_score=72,
            relevance_score=100,
            final_score=84,
            alert_level="immediate_alert",
            first_seen_at=datetime(2026, 5, 29, 13, 0, tzinfo=UTC),
            last_updated_at=datetime(2026, 5, 29, 13, 10, tzinfo=UTC),
            created_at=datetime(2026, 5, 29, 13, 0, tzinfo=UTC),
            updated_at=datetime(2026, 5, 29, 13, 10, tzinfo=UTC),
        )
        news = NormalizedNewsItem(
            id="news_1",
            source_id="src_1",
            title="Fed signals a slower rate path",
            url="https://example.com/news",
            source_name="Federal Reserve",
            source_type="official",
            source_score=100,
            region="us",
            asset_classes=["global_macro"],
            processing_status="clustered",
            title_hash="mock_title_hash",
            normalized_text_hash="mock_text_hash",
        )
        alert = AlertDecision(
            id="alert_1",
            event_cluster_id="evt_1",
            decision="immediate_alert",
            reason="score_above_immediate_threshold",
            score_breakdown={"final_score": 84},
            channel="telegram",
            created_at=datetime(2026, 5, 29, 13, 5, tzinfo=UTC),
        )
        channel = AlertChannel(
            id="chan_1",
            name="Primary Telegram",
            channel_type="telegram",
            config={"chat_id": "chat_1"},
            enabled=True,
            is_default=True,
        )
        suppression_rule = AlertSuppressionRule(
            id="rule_1",
            name="Quiet hours",
            rule_type="quiet_hours",
            config={"start_hour": 23, "end_hour": 7, "timezone": "Asia/Ho_Chi_Minh"},
            enabled=True,
        )
        job = JobRun(
            id="jobrun_1",
            job_name="pipeline",
            status="success",
            result={
                "clusters": 1,
                "pipeline_metrics": {
                    "status": "success",
                    "started_at": "2026-05-29T13:00:00+00:00",
                    "completed_at": "2026-05-29T13:00:02+00:00",
                    "duration_ms": 2000,
                    "stages": [
                        {
                            "stage_name": "poll_sources",
                            "start_time": "2026-05-29T13:00:00+00:00",
                            "end_time": "2026-05-29T13:00:01+00:00",
                            "duration_ms": 1000,
                            "items_in": 1,
                            "items_out": 5,
                            "status": "success",
                        }
                    ],
                    "slow_stages": [],
                },
            },
            started_at=datetime(2026, 5, 29, tzinfo=UTC),
            completed_at=datetime(2026, 5, 29, tzinfo=UTC),
        )
        command = BotCommand(
            id="cmd_1",
            command_type="pipeline.run",
            status="succeeded",
            payload={"dry_run": True},
            result={"event_clusters": 1},
            created_at=datetime(2026, 5, 29, 13, 2, tzinfo=UTC),
            completed_at=datetime(2026, 5, 29, 13, 3, tzinfo=UTC),
        )
        watch = WatchlistEntity(
            id="watch_1",
            symbol="SPY",
            name="S&P 500 ETF",
            entity_type="etf",
            tier="S",
            region="us",
            asset_class="equity",
            aliases=["SPDR S&P 500"],
            enabled=True,
        )
        presets = AppSetting(
            key="configuration_presets",
            value={
                "sources": {
                    "source_types": ["rss"],
                    "regions": ["global", "asia", "us", "vietnam", "china", "crypto", "other"],
                    "categories": [
                        "global_macro",
                        "us_equity",
                        "vietnam_equity",
                        "crypto",
                        "commodity",
                        "fx",
                        "rates",
                        "geopolitics",
                        "company_disclosure",
                        "exchange_announcement",
                    ],
                    "languages": ["en", "vi", "zh", "ja", "multi"],
                },
                "watchlist": {
                    "entity_types": [
                        "equity",
                        "etf",
                        "crypto",
                        "macro_theme",
                        "commodity",
                        "currency",
                        "sector",
                        "company",
                        "index",
                    ],
                    "tiers": ["S", "A", "B", "C", "D"],
                    "regions": ["global", "asia", "us", "vietnam", "china", "crypto", "other"],
                    "asset_classes": [
                        "equity",
                        "crypto",
                        "global_macro",
                        "vietnam_equity",
                        "us_equity",
                        "commodity",
                        "fx",
                        "rates",
                        "credit",
                    ],
                },
            },
        )
        fetch_log = SourceFetchLog(
            id="fetch_1",
            source_id="src_1",
            status="success",
            duration_ms=120,
            item_count=5,
            fetched_at=datetime(2026, 5, 29, 12, 55, tzinfo=UTC),
        )
        cluster_item = EventClusterItem(
            event_cluster_id="evt_1",
            news_item_id="news_1",
            relation_type="seed",
            similarity_score=91,
            added_at=datetime(2026, 5, 29, 13, 1, tzinfo=UTC),
        )
        score_history = EventScoreHistory(
            id="score_1",
            event_cluster_id="evt_1",
            score_breakdown={
                "source_score": 100,
                "impact_score": 75,
                "relevance_score": 100,
                "novelty_score": 85,
                "urgency_score": 80,
                "market_move_score": 72,
                "confidence_score": 88,
                "duplicate_penalty": 0,
                "noise_penalty": 0,
                "stale_penalty": 0,
                "final_score": 84,
            },
            final_score=84,
            created_at=datetime(2026, 5, 29, 13, 4, tzinfo=UTC),
        )
        catalyst = MissedCatalystReview(
            id="review_1",
            asset_symbol="SPY",
            asset_class="equity",
            move_window="1h",
            price_change_pct=5.5,
            status="pending",
        )
        news_embedding = NewsItemEmbedding(
            news_item_id="news_1",
            provider="openai",
            embedding_model="text-embedding-3-small",
            embedding_version="1",
            dimensions=1536,
            embedding_text_hash="hash_1",
            vector=[0.1]*1536,
        )
        event_embedding = EventClusterEmbedding(
            event_cluster_id="evt_1",
            provider="openai",
            embedding_model="text-embedding-3-small",
            embedding_version="1",
            dimensions=1536,
            embedding_text_hash="hash_2",
            vector=[0.2]*1536,
        )
        llm_run = LLMAnalysisRun(
            id="llm_1",
            target_type="event_cluster",
            target_id="evt_1",
            provider="openai",
            model="gpt-4o",
            prompt_version="1",
            prompt_hash="phash",
            status="succeeded",
            result={"summary": "Less hawkish Fed path.", "risk_flags": ["rates"]},
            usage={"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
            created_at=datetime(2026, 5, 29, 13, 7, tzinfo=UTC),
        )
        investigation = AgentInvestigation(
            id="inv_1",
            target_type="event_cluster",
            target_id="evt_1",
            trigger_reason="dashboard_test",
            status="succeeded",
            evidence=[{"source": "official", "title": "Fed statement"}],
            result={"suggested_action": "monitor duration exposure"},
            created_at=datetime(2026, 5, 29, 13, 6, tzinfo=UTC),
        )
        market_move = MarketMove(
            id="move_1",
            asset_symbol="SPY",
            asset_class="equity",
            exchange="NYSE",
            timestamp=datetime(2026, 5, 29, 13, 10, tzinfo=UTC),
            window="1h",
            price_change_pct=1.7,
            volume_change_pct=22.5,
        )
        retention = RetentionJob(
            id="retention_1",
            status="completed",
            deleted_counts={"news": 10},
        )
        session.add_all([
            source, event, news, alert, channel, suppression_rule, job, command, watch, presets,
            fetch_log, cluster_item, score_history, catalyst, news_embedding,
            event_embedding, llm_run, investigation, market_move, retention
        ])
        await session.commit()

    async def override_session():
        async with factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_session] = override_session
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    await engine.dispose()


@pytest.mark.asyncio
async def test_monitoring_endpoints_return_existing_bot_data(client: AsyncClient) -> None:
    health = await client.get("/health")
    assert health.status_code == 200
    assert health.json()["status"] == "ok"

    ready = await client.get("/ready")
    assert ready.status_code == 200
    assert ready.json()["status"] == "ready"
    assert set(ready.json()["pool"]) == {"pool_size", "checked_out", "overflow"}

    status = await client.get("/bot/status")
    assert status.status_code == 200
    assert status.json()["latest_job"]["id"] == "jobrun_1"

    sources = await client.get("/sources")
    assert sources.status_code == 200
    assert sources.json()["items"][0]["name"] == "Federal Reserve"

    events = await client.get("/events")
    assert events.status_code == 200
    assert events.json()["items"][0]["final_score"] == 84

    event = await client.get("/events/evt_1")
    assert event.status_code == 200
    assert event.json()["latest_alert"]["id"] == "alert_1"

    news = await client.get("/news")
    assert news.status_code == 200
    assert news.json()["items"][0]["processing_status"] == "clustered"

    alerts = await client.get("/alerts")
    assert alerts.status_code == 200
    assert alerts.json()["items"][0]["event"]["id"] == "evt_1"
    assert alerts.json()["items"][0]["acknowledged_at"] is None

    channels = await client.get("/alert-channels")
    assert channels.status_code == 200
    assert channels.json()["items"][0]["name"] == "Primary Telegram"

    rules = await client.get("/alert-suppression-rules")
    assert rules.status_code == 200
    assert rules.json()["items"][0]["rule_type"] == "quiet_hours"


@pytest.mark.asyncio
async def test_event_detail_includes_timeline_analysis_investigation_and_market_moves(
    client: AsyncClient,
) -> None:
    response = await client.get("/events/evt_1")

    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == "evt_1"
    assert payload["timeline"][0]["news_item_id"] == "news_1"
    assert payload["timeline"][0]["title"] == "Fed signals a slower rate path"
    assert payload["timeline"][0]["source_name"] == "Federal Reserve"
    assert payload["score_history"][0]["score_breakdown"]["market_move_score"] == 72
    assert payload["llm_runs"][0]["id"] == "llm_1"
    assert payload["llm_runs"][0]["result"]["summary"] == "Less hawkish Fed path."
    assert payload["latest_investigation"]["id"] == "inv_1"
    assert payload["latest_investigation"]["result"]["suggested_action"] == (
        "monitor duration exposure"
    )
    assert payload["market_moves"][0]["asset_symbol"] == "SPY"
    assert payload["market_moves"][0]["price_change_pct"] == 1.7


@pytest.mark.asyncio
async def test_source_health_endpoint_reports_status_latency_and_daily_counts(
    client: AsyncClient,
) -> None:
    response = await client.get("/sources/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    source = payload["items"][0]
    assert source["source_id"] == "src_1"
    assert source["name"] == "Federal Reserve"
    assert source["health_status"] == "healthy"
    assert source["latest_status"] == "success"
    assert source["average_latency_ms"] == 120
    assert source["consecutive_failure_count"] == 0
    assert source["daily_item_counts"] == [{"date": "2026-05-29", "count": 5}]


@pytest.mark.asyncio
async def test_source_health_endpoint_reports_disabled_sources_as_disabled(
    client: AsyncClient,
) -> None:
    response = await client.post("/sources/src_1/disable", headers=AUTH_HEADERS)
    assert response.status_code == 200

    health = await client.get("/sources/health")

    assert health.status_code == 200
    source = health.json()["items"][0]
    assert source["enabled"] is False
    assert source["health_status"] == "disabled"


@pytest.mark.asyncio
async def test_source_preview_parses_rss_without_writing_fetch_logs(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from api_server.app.services import sources as source_service

    async def fake_preview_source_url(
        *, url: str, source_type: str, limit: int
    ) -> SourcePreviewResult:
        assert url == "https://example.com/feed.xml"
        assert source_type == "rss"
        assert limit == 10
        return SourcePreviewResult.from_rss(
            url=url,
            source_type=source_type,
            http_status=200,
            duration_ms=12,
            body="""<?xml version="1.0" encoding="UTF-8"?>
            <rss version="2.0"><channel><item>
              <title>Oil jumps on shipping disruption</title>
              <link>https://example.com/oil</link>
              <description>Brent rises after a tanker incident.</description>
              <pubDate>Mon, 25 May 2026 03:00:00 GMT</pubDate>
              <guid>oil-1</guid>
            </item></channel></rss>""",
            limit=limit,
        )

    monkeypatch.setattr(source_service, "preview_source_url", fake_preview_source_url)

    before_logs = await client.get("/source-fetch-logs")
    response = await client.post(
        "/sources/preview",
        headers=AUTH_HEADERS,
        json={"url": "https://example.com/feed.xml", "source_type": "rss", "limit": 10},
    )
    after_logs = await client.get("/source-fetch-logs")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "success"
    assert payload["http_status"] == 200
    assert payload["item_count"] == 1
    assert payload["items"][0]["title"] == "Oil jumps on shipping disruption"
    assert payload["items"][0]["url"] == "https://example.com/oil"
    assert payload["items"][0]["description"] == "Brent rises after a tanker incident."
    assert before_logs.json()["total"] == after_logs.json()["total"] == 1


@pytest.mark.asyncio
async def test_source_preview_reports_blocked_fetch_without_db_writes(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from api_server.app.services import sources as source_service

    async def fake_preview_source_url(
        *, url: str, source_type: str, limit: int
    ) -> SourcePreviewResult:
        return SourcePreviewResult(
            status="error",
            url=url,
            source_type=source_type,
            http_status=403,
            duration_ms=8,
            item_count=0,
            items=[],
            error_message="HTTPStatusError: forbidden",
        )

    monkeypatch.setattr(source_service, "preview_source_url", fake_preview_source_url)

    before_logs = await client.get("/source-fetch-logs")
    response = await client.post(
        "/sources/preview",
        headers=AUTH_HEADERS,
        json={"url": "https://example.com/blocked.xml", "source_type": "rss"},
    )
    after_logs = await client.get("/source-fetch-logs")

    assert response.status_code == 200
    assert response.json()["status"] == "error"
    assert response.json()["http_status"] == 403
    assert "forbidden" in response.json()["error_message"]
    assert before_logs.json()["total"] == after_logs.json()["total"] == 1


@pytest.mark.asyncio
async def test_source_article_preview_extracts_and_caps_text(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from api_server.app.services import sources as source_service

    async def fake_preview_article_url(
        *, url: str, fallback_snippet: str | None, max_chars: int
    ) -> ArticlePreviewResult:
        assert url == "https://example.com/oil"
        assert fallback_snippet == "RSS fallback"
        assert max_chars == 20
        return ArticlePreviewResult.from_text(
            url=url,
            http_status=200,
            duration_ms=15,
            text="Readable article text from the publisher",
            max_chars=max_chars,
        )

    monkeypatch.setattr(source_service, "preview_article_url", fake_preview_article_url)

    response = await client.post(
        "/sources/preview/article",
        headers=AUTH_HEADERS,
        json={
            "url": "https://example.com/oil",
            "fallback_snippet": "RSS fallback",
            "max_chars": 20,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "success"
    assert payload["http_status"] == 200
    assert payload["text"] == "Readable article tex"
    assert payload["text_length"] == len("Readable article text from the publisher")
    assert payload["truncated"] is True


@pytest.mark.asyncio
async def test_source_preview_rejects_missing_or_invalid_url(client: AsyncClient) -> None:
    response = await client.post(
        "/sources/preview",
        headers=AUTH_HEADERS,
        json={"url": "", "source_type": "rss"},
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_maintenance_observability_endpoints_return_costs_and_pipeline_metrics(
    client: AsyncClient,
) -> None:
    costs = await client.get("/maintenance/llm-costs")

    assert costs.status_code == 200
    cost_payload = costs.json()
    assert cost_payload["daily"][0]["date"] == "2026-05-29"
    assert cost_payload["daily"][0]["total_tokens"] == 150
    assert cost_payload["weekly"]["total_tokens"] == 150
    assert cost_payload["by_model"][0]["model"] == "gpt-4o"
    assert cost_payload["by_analysis_type"][0]["analysis_type"] == "event_cluster"

    metrics = await client.get("/maintenance/pipeline-metrics")

    assert metrics.status_code == 200
    metric_payload = metrics.json()
    assert metric_payload["items"][0]["job_run_id"] == "jobrun_1"
    assert metric_payload["items"][0]["stages"][0]["stage_name"] == "poll_sources"
    assert metric_payload["items"][0]["stages"][0]["duration_ms"] == 1000


@pytest.mark.asyncio
async def test_event_stream_emits_heartbeat_and_existing_change_events(client: AsyncClient) -> None:
    async with client.stream("GET", "/events/stream?replay=true&limit=4") as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        body = ""
        async for chunk in response.aiter_text():
            body += chunk
            if body.count("\n\n") >= 4:
                break

    assert "event: heartbeat" in body
    assert "event: alert.created" in body
    assert "event: pipeline.completed" in body
    assert "event: command.updated" in body
    assert '"id":"alert_1"' in body
    assert '"id":"jobrun_1"' in body
    assert '"id":"cmd_1"' in body


@pytest.mark.asyncio
async def test_alert_controls_crud_acknowledge_and_channel_test_command(
    client: AsyncClient,
) -> None:
    created_channel = await client.post(
        "/alert-channels",
        headers=AUTH_HEADERS,
        json={
            "name": "Webhook",
            "channel_type": "webhook",
            "config": {"url": "https://hooks.example.test/alert"},
            "enabled": True,
            "is_default": False,
        },
    )
    assert created_channel.status_code == 201
    channel_id = created_channel.json()["id"]

    patched_channel = await client.patch(
        f"/alert-channels/{channel_id}",
        headers=AUTH_HEADERS,
        json={"enabled": False},
    )
    assert patched_channel.status_code == 200
    assert patched_channel.json()["enabled"] is False

    test_command = await client.post(
        f"/alert-channels/{channel_id}/test",
        headers=AUTH_HEADERS,
        json={"message": "hello"},
    )
    assert test_command.status_code == 201
    assert test_command.json()["command_type"] == "alert.test_channel"
    assert test_command.json()["payload"]["channel_id"] == channel_id

    created_rule = await client.post(
        "/alert-suppression-rules",
        headers=AUTH_HEADERS,
        json={
            "name": "Mute BTC",
            "rule_type": "entity_mute",
            "config": {"entities": ["BTC"]},
            "enabled": True,
        },
    )
    assert created_rule.status_code == 201
    rule_id = created_rule.json()["id"]

    patched_rule = await client.patch(
        f"/alert-suppression-rules/{rule_id}",
        headers=AUTH_HEADERS,
        json={"enabled": False},
    )
    assert patched_rule.status_code == 200
    assert patched_rule.json()["enabled"] is False

    acknowledged = await client.post("/alerts/alert_1/acknowledge", headers=AUTH_HEADERS)
    assert acknowledged.status_code == 200
    assert acknowledged.json()["acknowledged_at"] is not None

    dismissed = await client.post("/alerts/alert_1/dismiss", headers=AUTH_HEADERS)
    assert dismissed.status_code == 200
    assert dismissed.json()["suppression_reason"] == "dismissed"

    deleted_rule = await client.delete(
        f"/alert-suppression-rules/{rule_id}",
        headers=AUTH_HEADERS,
    )
    assert deleted_rule.status_code == 204

    deleted_channel = await client.delete(f"/alert-channels/{channel_id}", headers=AUTH_HEADERS)
    assert deleted_channel.status_code == 204


@pytest.mark.asyncio
async def test_ready_returns_503_when_database_check_fails() -> None:
    class BrokenReadinessSession:
        async def execute(self, _stmt):
            raise SQLAlchemyError("database unavailable")

    async def override_session():
        yield BrokenReadinessSession()

    app.state.settings = Settings(database_url="sqlite+aiosqlite:///:memory:")
    app.dependency_overrides[get_session] = override_session
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as test_client:
        response = await test_client.get("/ready")
    app.dependency_overrides.clear()

    assert response.status_code == 503
    assert response.json()["status"] == "not_ready"


@pytest.mark.asyncio
async def test_private_network_dashboard_origin_is_allowed(client: AsyncClient) -> None:
    response = await client.get("/health", headers={"Origin": "http://192.168.28.40:5173"})

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://192.168.28.40:5173"


@pytest.mark.asyncio
async def test_safe_configuration_and_command_endpoints(client: AsyncClient) -> None:
    created = await client.post(
        "/sources",
        headers=AUTH_HEADERS,
        json={
            "name": "CoinDesk",
            "url": "https://example.com/coindesk",
            "region": "crypto",
            "category": "crypto",
            "source_type": "rss",
            "language": "en",
            "source_score": 75,
            "polling_interval_seconds": 600,
        },
    )
    assert created.status_code == 201
    source_id = created.json()["id"]

    disabled = await client.post(f"/sources/{source_id}/disable", headers=AUTH_HEADERS)
    assert disabled.status_code == 200
    assert disabled.json()["enabled"] is False

    unauthenticated_bulk = await client.post("/sources/bulk-enabled", json={"enabled": False})
    assert unauthenticated_bulk.status_code == 401

    bulk_disabled = await client.post(
        "/sources/bulk-enabled",
        headers=AUTH_HEADERS,
        json={"enabled": False},
    )
    assert bulk_disabled.status_code == 200
    assert bulk_disabled.json()["total"] == 2
    assert all(row["enabled"] is False for row in bulk_disabled.json()["items"])

    bulk_enabled = await client.post(
        "/sources/bulk-enabled",
        headers=AUTH_HEADERS,
        json={"enabled": True},
    )
    assert bulk_enabled.status_code == 200
    assert bulk_enabled.json()["total"] == 2
    assert all(row["enabled"] is True for row in bulk_enabled.json()["items"])

    watchlist = await client.get("/watchlist")
    assert watchlist.status_code == 200
    assert watchlist.json()["items"][0]["symbol"] == "SPY"
    assert watchlist.json()["items"][0]["tier"] == "S"

    policy = await client.patch(
        "/settings/alert-policy",
        headers=AUTH_HEADERS,
        json={
            "immediate_threshold": 81,
            "watchlist_threshold": 56,
            "digest_threshold": 31,
            "default_channel": "telegram",
        },
    )
    assert policy.status_code == 200
    assert policy.json()["immediate_threshold"] == 81

    command = await client.post(
        "/bot/commands",
        headers=AUTH_HEADERS,
        json={"command_type": "pipeline.run", "payload": {"dry_run": True}},
    )
    assert command.status_code == 201
    assert command.json()["status"] == "pending"

    listed = await client.get("/bot/commands")
    assert listed.status_code == 200
    assert listed.json()["items"][0]["command_type"] == "pipeline.run"

    cancelled = await client.post(
        f"/bot/commands/{command.json()['id']}/cancel",
        headers=AUTH_HEADERS,
    )
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"


@pytest.mark.asyncio
async def test_safe_configuration_mutations_normalize_tier_and_delete_watchlist(
    client: AsyncClient,
) -> None:
    patched_source = await client.patch(
        "/sources/src_1",
        headers=AUTH_HEADERS,
        json={
            "name": "Federal Reserve Watch",
            "url": "https://example.com/fed-watch",
            "category": "rates",
            "source_score": 95,
            "enabled": False,
        },
    )

    assert patched_source.status_code == 200
    assert patched_source.json()["name"] == "Federal Reserve Watch"
    assert patched_source.json()["category"] == "rates"
    assert patched_source.json()["asset_classes"] == ["rates"]
    assert patched_source.json()["enabled"] is False

    created_watch = await client.post(
        "/watchlist",
        headers=AUTH_HEADERS,
        json={
            "symbol": "btc",
            "name": "Bitcoin",
            "entity_type": "crypto",
            "tier": "s",
            "region": "global",
            "asset_class": "crypto",
            "aliases": ["digital gold"],
            "enabled": True,
        },
    )

    assert created_watch.status_code == 201
    assert created_watch.json()["tier"] == "S"
    watch_id = created_watch.json()["id"]

    updated_watch = await client.patch(
        f"/watchlist/{watch_id}",
        headers=AUTH_HEADERS,
        json={"tier": "a", "aliases": ["BTC"]},
    )

    assert updated_watch.status_code == 200
    assert updated_watch.json()["tier"] == "A"
    assert updated_watch.json()["aliases"] == ["BTC"]

    deleted_watch = await client.delete(f"/watchlist/{watch_id}", headers=AUTH_HEADERS)
    assert deleted_watch.status_code == 204

    missing_watch = await client.get("/watchlist")
    assert all(row["id"] != watch_id for row in missing_watch.json()["items"])


@pytest.mark.asyncio
async def test_alert_policy_defaults_and_updates(client: AsyncClient) -> None:
    default_policy = await client.get("/settings/alert-policy")

    assert default_policy.status_code == 200
    assert default_policy.json() == {
        "immediate_threshold": 80,
        "watchlist_threshold": 55,
        "digest_threshold": 30,
        "default_channel": "log",
    }

    updated_policy = await client.patch(
        "/settings/alert-policy",
        headers=AUTH_HEADERS,
        json={
            "immediate_threshold": 85,
            "watchlist_threshold": 60,
            "digest_threshold": 35,
            "default_channel": "telegram",
        },
    )

    assert updated_policy.status_code == 200
    assert updated_policy.json()["default_channel"] == "telegram"


@pytest.mark.asyncio
async def test_configuration_presets_are_served_by_api(client: AsyncClient) -> None:
    response = await client.get("/settings/presets")

    assert response.status_code == 200
    payload = response.json()
    assert payload["sources"]["source_types"] == ["rss"]
    assert "vietnam" in payload["sources"]["regions"]
    assert "crypto" in payload["sources"]["categories"]
    assert payload["sources"]["languages"] == ["en", "vi", "zh", "ja", "multi"]
    assert payload["watchlist"]["tiers"] == ["S", "A", "B", "C", "D"]
    assert "etf" in payload["watchlist"]["entity_types"]
    assert "equity" in payload["watchlist"]["asset_classes"]

    # Assert dynamic alert presets
    assert "alerts" in payload
    assert len(payload["alerts"]["channels"]) > 0
    assert len(payload["alerts"]["rules"]) > 0

    webhook_preset = next(c for c in payload["alerts"]["channels"] if c["type"] == "webhook")
    assert webhook_preset["placeholder"] == "e.g. Discord Webhook Alerts"
    assert "url" in webhook_preset["template"]

    cooldown_preset = next(r for r in payload["alerts"]["rules"] if r["type"] == "cooldown")
    assert cooldown_preset["placeholder"] == "e.g. 6-Hour Cooldown"
    assert cooldown_preset["template"]["hours"] == 6


@pytest.mark.asyncio
async def test_source_create_rejects_unsupported_source_type(client: AsyncClient) -> None:
    response = await client.post(
        "/sources",
        headers=AUTH_HEADERS,
        json={
            "name": "Unsupported API Source",
            "url": "https://example.com/source-api",
            "region": "global",
            "category": "global_macro",
            "source_type": "api",
            "language": "en",
            "source_score": 60,
            "polling_interval_seconds": 600,
        },
    )

    assert response.status_code == 422
    assert "unsupported source_type" in response.json()["detail"][0]["msg"].lower()


@pytest.mark.asyncio
async def test_source_create_accepts_crawler_source_type(client: AsyncClient) -> None:
    response = await client.post(
        "/sources",
        headers=AUTH_HEADERS,
        json={
            "name": "Reuters Business Crawler",
            "url": "https://www.reuters.com/business/",
            "region": "global",
            "category": "global_macro",
            "source_type": "crawler",
            "language": "en",
            "source_score": 85,
            "polling_interval_seconds": 600,
        },
    )

    assert response.status_code == 201
    assert response.json()["source_type"] == "crawler"


@pytest.mark.asyncio
async def test_source_create_accepts_google_rss_source_type(client: AsyncClient) -> None:
    response = await client.post(
        "/sources",
        headers=AUTH_HEADERS,
        json={
            "name": "FT Google RSS",
            "url": "https://news.google.com/rss/search?q=site:ft.com+markets",
            "region": "global",
            "category": "global_macro",
            "source_type": "google-rss",
            "language": "en",
            "source_score": 60,
            "polling_interval_seconds": 1800,
        },
    )

    assert response.status_code == 201
    assert response.json()["source_type"] == "google-rss"


@pytest.mark.asyncio
async def test_source_update_rejects_unsupported_source_type(client: AsyncClient) -> None:
    created = await client.post(
        "/sources",
        headers=AUTH_HEADERS,
        json={
            "name": "RSS Source",
            "url": "https://example.com/rss-source",
            "region": "global",
            "category": "global_macro",
            "source_type": "rss",
            "language": "en",
            "source_score": 60,
            "polling_interval_seconds": 600,
        },
    )
    assert created.status_code == 201

    response = await client.patch(
        f"/sources/{created.json()['id']}",
        headers=AUTH_HEADERS,
        json={"source_type": "official"},
    )

    assert response.status_code == 422
    assert "unsupported source_type" in response.json()["detail"][0]["msg"].lower()


@pytest.mark.asyncio
async def test_source_update_accepts_google_rss_source_type(client: AsyncClient) -> None:
    created = await client.post(
        "/sources",
        headers=AUTH_HEADERS,
        json={
            "name": "RSS Source For Google Update",
            "url": "https://example.com/rss-source-update",
            "region": "global",
            "category": "global_macro",
            "source_type": "rss",
            "language": "en",
            "source_score": 60,
            "polling_interval_seconds": 600,
        },
    )
    assert created.status_code == 201

    response = await client.patch(
        f"/sources/{created.json()['id']}",
        headers=AUTH_HEADERS,
        json={"source_type": "google-rss"},
    )

    assert response.status_code == 200
    assert response.json()["source_type"] == "google-rss"


@pytest.mark.asyncio
async def test_rejects_unknown_bot_command(client: AsyncClient) -> None:
    response = await client.post(
        "/bot/commands",
        headers=AUTH_HEADERS,
        json={"command_type": "shell.exec", "payload": {}},
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_bot_status_degrades_when_command_table_is_missing() -> None:
    class MissingCommandTableSession:
        def __init__(self) -> None:
            self.calls = 0
            self.rollbacks = 0

        async def scalar(self, _stmt):
            self.calls += 1
            if self.calls == 1:
                return None
            raise SQLAlchemyError("relation bot_commands does not exist")

        async def rollback(self):
            self.rollbacks += 1

    missing_session = MissingCommandTableSession()

    async def override_session():
        yield missing_session

    app.dependency_overrides[get_session] = override_session
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as test_client:
        response = await test_client.get("/bot/status")
    app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["pending_commands"] == 0
    assert response.json()["running_commands"] == 0
    assert response.json()["latest_job_available"] is True
    assert response.json()["command_queue_available"] is False
    assert missing_session.rollbacks == 2


@pytest.mark.asyncio
async def test_bot_status_degrades_when_job_table_is_missing() -> None:
    class MissingJobTableSession:
        def __init__(self) -> None:
            self.rollbacks = 0

        async def scalar(self, _stmt):
            raise SQLAlchemyError("relation job_runs does not exist")

        async def rollback(self):
            self.rollbacks += 1

    missing_session = MissingJobTableSession()

    async def override_session():
        yield missing_session

    app.dependency_overrides[get_session] = override_session
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as test_client:
        response = await test_client.get("/bot/status")
    app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["latest_job"] is None
    assert response.json()["latest_job_available"] is False
    assert response.json()["command_queue_available"] is False
    assert missing_session.rollbacks == 3


@pytest.mark.asyncio
async def test_command_payload_validation_accepts_valid_payloads(client: AsyncClient) -> None:
    valid_commands = [
        ("pipeline.run", {"dry_run": True}),
        ("pipeline.run", {}),
        ("source.fetch", {"source_id": "src_1"}),
        ("alert.dispatch", {"channel": "telegram", "limit": 10, "dry_run": True}),
        ("alert.dispatch", {}),
        ("event.rescore", {"event_id": "evt_1"}),
        ("event.mark", {"event_id": "evt_1", "status": "confirmed"}),
        ("event.recluster", {"since": "48h", "limit": 100, "apply": False}),
        ("event.recluster", {}),
        ("investigation.run_event", {"event_id": "evt_1"}),
        ("retention.preview", {}),
        ("retention.run", {}),
    ]
    for command_type, payload in valid_commands:
        response = await client.post(
            "/bot/commands",
            headers=AUTH_HEADERS,
            json={"command_type": command_type, "payload": payload},
        )
        assert response.status_code == 201, (
            f"{command_type} with {payload} returned {response.status_code}: "
            f"{response.text}"
        )
        assert response.json()["status"] == "pending"


@pytest.mark.asyncio
async def test_command_payload_validation_rejects_invalid_payloads(client: AsyncClient) -> None:
    invalid_commands = [
        ("source.fetch", {}, "Missing required"),
        ("source.fetch", {"source_id": 123}, "must be str"),
        ("event.rescore", {}, "Missing required"),
        ("event.mark", {"event_id": "evt_1"}, "Missing required"),
        ("event.mark", {"event_id": "evt_1", "status": "invalid"}, "Invalid event status"),
        ("investigation.run_event", {}, "Missing required"),
        ("pipeline.run", {"dry_run": "yes"}, "must be bool"),
        ("pipeline.run", {"unknown_key": True}, "Unexpected payload key"),
        ("retention.run", {"extra": 1}, "Unexpected payload key"),
    ]
    for command_type, payload, _reason in invalid_commands:
        response = await client.post(
            "/bot/commands",
            headers=AUTH_HEADERS,
            json={"command_type": command_type, "payload": payload},
        )
        assert response.status_code == 422, (
            f"{command_type} with {payload} should be 422 ({_reason}), "
            f"got {response.status_code}: {response.text}"
        )


@pytest.mark.asyncio
async def test_creating_command_returns_503_when_table_missing() -> None:
    class BrokenSession:
        def add(self, _obj):
            pass

        async def flush(self):
            raise SQLAlchemyError("relation bot_commands does not exist")

        async def rollback(self):
            pass

    async def override_session():
        yield BrokenSession()

    app.state.settings = Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        api_auth_token="test-token",
    )
    app.dependency_overrides[get_session] = override_session
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as test_client:
        response = await test_client.post(
            "/bot/commands",
            headers=AUTH_HEADERS,
            json={"command_type": "pipeline.run", "payload": {"dry_run": True}},
        )
    app.dependency_overrides.clear()

    assert response.status_code == 503
    assert "migrate" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_mutating_endpoints_require_bearer_token(client: AsyncClient) -> None:
    open_response = await client.get("/sources")
    assert open_response.status_code == 200

    payload = {
        "name": "CoinDesk Auth",
        "url": "https://example.com/coindesk-auth",
        "region": "crypto",
        "category": "crypto",
        "source_type": "rss",
        "language": "en",
        "source_score": 75,
        "polling_interval_seconds": 600,
    }

    missing = await client.post(
        "/sources",
        headers={"Origin": "http://localhost:5173"},
        json=payload,
    )
    assert missing.status_code == 401
    assert missing.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert missing.headers["access-control-allow-credentials"] == "true"

    invalid = await client.post(
        "/sources",
        headers={
            "Authorization": "Bearer wrong-token",
            "Origin": "http://localhost:5173",
        },
        json=payload,
    )
    assert invalid.status_code == 403
    assert invalid.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert invalid.headers["access-control-allow-credentials"] == "true"

    valid = await client.post("/sources", headers=AUTH_HEADERS, json=payload)
    assert valid.status_code == 201


@pytest.mark.asyncio
async def test_maintenance_endpoints(client: AsyncClient) -> None:
    # 1. Fetch Logs
    response = await client.get("/maintenance/fetch-logs")
    assert response.status_code == 200
    data = response.json()
    assert "items" in data
    assert "total" in data
    assert data["total"] == 1
    assert data["items"][0]["id"] == "fetch_1"
    assert data["items"][0]["status"] == "success"
    assert data["items"][0]["source_id"] == "src_1"

    # 2. Score History
    response = await client.get("/maintenance/score-history")
    assert response.status_code == 200
    data = response.json()
    assert "items" in data
    assert data["total"] == 1
    assert data["items"][0]["id"] == "score_1"
    assert data["items"][0]["final_score"] == 84
    assert data["items"][0]["score_breakdown"]["relevance_score"] == 100

    # 3. Missed Catalysts
    response = await client.get("/maintenance/catalysts")
    assert response.status_code == 200
    data = response.json()
    assert "items" in data
    assert data["total"] == 1
    assert data["items"][0]["id"] == "review_1"
    assert data["items"][0]["asset_symbol"] == "SPY"
    assert data["items"][0]["price_change_pct"] == 5.5

    # 4. Embeddings Status
    response = await client.get("/maintenance/embeddings/stats")
    assert response.status_code == 200
    data = response.json()
    assert "total_news_items" in data
    assert data["news_items_with_embeddings"] == 1
    assert data["embedding_coverage_pct"] == 100.0
    assert data["event_clusters_with_embeddings"] == 1
    assert data["cluster_embedding_coverage_pct"] == 100.0
    assert "openai" in data["news_providers"]
    assert "text-embedding-3-small" in data["news_models"]

    # 5. LLM Diagnostics
    response = await client.get("/maintenance/llm-runs")
    assert response.status_code == 200
    data = response.json()
    assert "items" in data
    assert data["total"] == 1
    assert data["items"][0]["id"] == "llm_1"
    assert data["items"][0]["model"] == "gpt-4o"
    assert data["items"][0]["usage"]["total_tokens"] == 150

    # 6. Retention Logs
    response = await client.get("/maintenance/retention-jobs")
    assert response.status_code == 200
    data = response.json()
    assert "items" in data
    assert data["total"] == 1
    assert data["items"][0]["id"] == "retention_1"
    assert data["items"][0]["status"] == "completed"
    assert data["items"][0]["deleted_counts"] == {"news": 10}
