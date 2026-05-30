from __future__ import annotations

from datetime import UTC, datetime

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from api_server.app.db import Base, get_session
from api_server.app.main import app
from common.db.models import (
    AlertDecisionRecord as AlertDecision,
)
from common.db.models import (
    AppSetting,
    EventCluster,
    JobRun,
    NewsSource,
    NormalizedNewsItem,
    WatchlistEntity,
)


@pytest.fixture()
async def client():
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
            affected_tickers=[],
            source_count=2,
            top_source_score=100,
            final_score=84,
            alert_level="immediate_alert",
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
        )
        job = JobRun(
            id="jobrun_1",
            job_name="pipeline",
            status="success",
            result={"clusters": 1},
            started_at=datetime(2026, 5, 29, tzinfo=UTC),
            completed_at=datetime(2026, 5, 29, tzinfo=UTC),
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
                    "source_types": [
                        "rss",
                        "api",
                        "crawler",
                        "official",
                        "newsletter",
                        "social",
                        "market_data",
                    ],
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
        session.add_all([source, event, news, alert, job, watch, presets])
        await session.commit()

    async def override_session():
        async with factory() as session:
            yield session

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


@pytest.mark.asyncio
async def test_private_network_dashboard_origin_is_allowed(client: AsyncClient) -> None:
    response = await client.get("/health", headers={"Origin": "http://192.168.28.40:5173"})

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://192.168.28.40:5173"


@pytest.mark.asyncio
async def test_safe_configuration_and_command_endpoints(client: AsyncClient) -> None:
    created = await client.post(
        "/sources",
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

    disabled = await client.post(f"/sources/{source_id}/disable")
    assert disabled.status_code == 200
    assert disabled.json()["enabled"] is False

    watchlist = await client.get("/watchlist")
    assert watchlist.status_code == 200
    assert watchlist.json()["items"][0]["symbol"] == "SPY"
    assert watchlist.json()["items"][0]["tier"] == "S"

    policy = await client.patch(
        "/settings/alert-policy",
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
        json={"command_type": "pipeline.run", "payload": {"dry_run": True}},
    )
    assert command.status_code == 201
    assert command.json()["status"] == "pending"

    listed = await client.get("/bot/commands")
    assert listed.status_code == 200
    assert listed.json()["items"][0]["command_type"] == "pipeline.run"

    cancelled = await client.post(f"/bot/commands/{command.json()['id']}/cancel")
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"


@pytest.mark.asyncio
async def test_safe_configuration_mutations_normalize_tier_and_delete_watchlist(
    client: AsyncClient,
) -> None:
    patched_source = await client.patch(
        "/sources/src_1",
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
        json={"tier": "a", "aliases": ["BTC"]},
    )

    assert updated_watch.status_code == 200
    assert updated_watch.json()["tier"] == "A"
    assert updated_watch.json()["aliases"] == ["BTC"]

    deleted_watch = await client.delete(f"/watchlist/{watch_id}")
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
    assert payload["sources"]["source_types"] == [
        "rss",
        "api",
        "crawler",
        "official",
        "newsletter",
        "social",
        "market_data",
    ]
    assert "vietnam" in payload["sources"]["regions"]
    assert "crypto" in payload["sources"]["categories"]
    assert payload["sources"]["languages"] == ["en", "vi", "zh", "ja", "multi"]
    assert payload["watchlist"]["tiers"] == ["S", "A", "B", "C", "D"]
    assert "etf" in payload["watchlist"]["entity_types"]
    assert "equity" in payload["watchlist"]["asset_classes"]


@pytest.mark.asyncio
async def test_rejects_unknown_bot_command(client: AsyncClient) -> None:
    response = await client.post(
        "/bot/commands",
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
            json={"command_type": command_type, "payload": payload},
        )
        assert response.status_code == 422, (
            f"{command_type} with {payload} should be 422 ({_reason}), "
            f"got {response.status_code}: {response.text}"
        )


@pytest.mark.asyncio
async def test_creating_command_returns_503_when_table_missing() -> None:
    class BrokenSession:
        async def add(self, _obj):
            pass

        async def commit(self):
            raise SQLAlchemyError("relation bot_commands does not exist")

        async def rollback(self):
            pass

    async def override_session():
        yield BrokenSession()

    app.dependency_overrides[get_session] = override_session
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as test_client:
        response = await test_client.post(
            "/bot/commands",
            json={"command_type": "pipeline.run", "payload": {"dry_run": True}},
        )
    app.dependency_overrides.clear()

    assert response.status_code == 503
    assert "migrate" in response.json()["detail"].lower()
