from __future__ import annotations

from datetime import UTC, datetime

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db import Base, get_session
from app.main import app
from app.models import (
    AlertDecision,
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
        session.add_all([source, event, news, alert, job, watch])
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
