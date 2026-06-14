from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from bot_worker.services.external_providers import ProviderRetryPolicy
from common.config import Settings
from common.db.models import Base, MarketSymbolResolution, WatchlistEntity
from common.market_symbol_resolver import (
    resolution_to_market_request,
    resolve_watchlist_market_symbol,
    watchlist_market_symbol_requests,
)


@pytest.fixture()
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as active_session:
        yield active_session
    await engine.dispose()


def _settings(**market_data_overrides: object) -> Settings:
    settings = Settings(database_url="sqlite+aiosqlite:///:memory:")
    for key, value in market_data_overrides.items():
        setattr(settings.market_data, key, value)
    return settings


async def _entry(
    session,
    *,
    symbol: str | None,
    name: str = "Test Asset",
    region: str | None = None,
    asset_class: str | None = None,
    entity_type: str = "equity",
) -> WatchlistEntity:
    entry = WatchlistEntity(
        symbol=symbol,
        name=name,
        entity_type=entity_type,
        tier="D",
        region=region,
        asset_class=asset_class,
        aliases=[],
    )
    session.add(entry)
    await session.flush()
    return entry


@pytest.mark.asyncio
async def test_resolver_persists_skipped_resolution_for_entry_without_symbol(session) -> None:
    entry = await _entry(
        session,
        symbol=None,
        name="Fed policy",
        region="global",
        asset_class="global_macro",
        entity_type="macro_theme",
    )

    resolution = await resolve_watchlist_market_symbol(
        session,
        entry,
        settings=_settings(),
    )

    assert resolution.status == "skipped"
    assert resolution.provider is None
    assert resolution.provider_symbol is None
    assert resolution.reason == "watchlist entry has no symbol"
    persisted = await session.scalar(select(MarketSymbolResolution))
    assert persisted is not None
    assert persisted.watchlist_entity_id == entry.id


@pytest.mark.asyncio
async def test_resolver_persists_vietnam_resolution_without_provider_call(session) -> None:
    entry = await _entry(session, symbol="VIC", region="vietnam", asset_class="vietnam_equity")

    resolution = await resolve_watchlist_market_symbol(
        session,
        entry,
        settings=_settings(),
    )

    assert resolution.status == "resolved"
    assert resolution.provider == "vietnam_market"
    assert resolution.provider_symbol == "vic"
    assert resolution.reason is None
    assert resolution.resolved_at is not None


@pytest.mark.asyncio
async def test_resolver_derives_binance_crypto_symbol(session) -> None:
    entry = await _entry(session, symbol="BTC", region="crypto", asset_class="crypto")

    resolution = await resolve_watchlist_market_symbol(
        session,
        entry,
        settings=_settings(crypto_provider="binance"),
    )

    assert resolution.status == "resolved"
    assert resolution.provider == "binance"
    assert resolution.provider_symbol == "BTCUSDT"


@pytest.mark.asyncio
async def test_resolver_uses_coingecko_symbol_map_for_crypto(session) -> None:
    entry = await _entry(session, symbol="XRP", region="crypto", asset_class="crypto")

    resolution = await resolve_watchlist_market_symbol(
        session,
        entry,
        settings=_settings(
            crypto_provider="coingecko",
            crypto_fallback_provider="binance",
            symbol_map={"XRP": "ripple"},
        ),
    )

    assert resolution.status == "resolved"
    assert resolution.provider == "coingecko"
    assert resolution.provider_symbol == "ripple"
    assert resolution_to_market_request(resolution).fallback_provider == "binance"


@pytest.mark.asyncio
async def test_resolver_marks_unmapped_coingecko_crypto_unresolved(session) -> None:
    entry = await _entry(session, symbol="NEWCOIN", region="crypto", asset_class="crypto")

    resolution = await resolve_watchlist_market_symbol(
        session,
        entry,
        settings=_settings(crypto_provider="coingecko", symbol_map={}),
    )

    assert resolution.status == "unresolved"
    assert resolution.provider == "coingecko"
    assert resolution.provider_symbol is None
    assert resolution.reason == "CoinGecko coin id is not configured for NEWCOIN"


@pytest.mark.asyncio
async def test_resolver_uses_hyperliquid_symbol_map_override(session) -> None:
    entry = await _entry(session, symbol="SPX", region="us", asset_class="index")

    resolution = await resolve_watchlist_market_symbol(
        session,
        entry,
        settings=_settings(symbol_map={"SPX": "xyz:SP500"}),
    )

    assert resolution.status == "resolved"
    assert resolution.provider == "hyperliquid"
    assert resolution.provider_symbol == "xyz:SP500"


@pytest.mark.asyncio
async def test_resolver_matches_hyperliquid_universe_when_no_override(session) -> None:
    class Client:
        async def request(self, method: str, url: str, **kwargs: object) -> httpx.Response:
            assert method == "POST"
            response = httpx.Response(
                200,
                json=[
                    {"universe": [{"name": "xyz:NVDA"}, {"name": "xyz:AAPL"}]},
                    [{"markPx": "100", "prevDayPx": "99"}, {"markPx": "200", "prevDayPx": "198"}],
                ],
            )
            response.request = httpx.Request(method, url)
            return response

    entry = await _entry(session, symbol="NVDA", region="us", asset_class="us_equity")

    resolution = await resolve_watchlist_market_symbol(
        session,
        entry,
        settings=_settings(symbol_map={}),
        client=Client(),
    )

    assert resolution.status == "resolved"
    assert resolution.provider == "hyperliquid"
    assert resolution.provider_symbol == "xyz:NVDA"
    assert resolution.resolution_metadata["match_source"] == "hyperliquid_universe"


@pytest.mark.asyncio
async def test_resolver_marks_hyperliquid_no_match_unresolved(session) -> None:
    class Client:
        async def request(self, method: str, url: str, **kwargs: object) -> httpx.Response:
            response = httpx.Response(200, json=[{"universe": [{"name": "xyz:AAPL"}]}, []])
            response.request = httpx.Request(method, url)
            return response

    entry = await _entry(session, symbol="ABCD", region="us", asset_class="us_equity")

    resolution = await resolve_watchlist_market_symbol(
        session,
        entry,
        settings=_settings(symbol_map={}),
        client=Client(),
    )

    assert resolution.status == "unresolved"
    assert resolution.provider == "hyperliquid"
    assert resolution.reason == "No Hyperliquid instrument matched ABCD"


@pytest.mark.asyncio
async def test_resolver_marks_unsupported_metadata_unresolved(session) -> None:
    entry = await _entry(
        session,
        symbol="THEME",
        region="other",
        asset_class="macro_theme",
        entity_type="macro_theme",
    )

    resolution = await resolve_watchlist_market_symbol(
        session,
        entry,
        settings=_settings(),
    )

    assert resolution.status == "unresolved"
    assert resolution.provider is None
    assert resolution.reason == "No resolver for region=other asset_class=macro_theme"


@pytest.mark.asyncio
async def test_resolver_stores_provider_failure_as_unresolved(session) -> None:
    class Client:
        async def request(self, method: str, url: str, **kwargs: object) -> httpx.Response:
            raise httpx.ConnectError("network down", request=httpx.Request(method, url))

    entry = await _entry(session, symbol="NVDA", region="us", asset_class="us_equity")

    resolution = await resolve_watchlist_market_symbol(
        session,
        entry,
        settings=_settings(symbol_map={}),
        client=Client(),
    )

    assert resolution.status == "unresolved"
    assert resolution.provider == "hyperliquid"
    assert resolution.provider_symbol is None
    assert "network down" in str(resolution.reason)


@pytest.mark.asyncio
async def test_resolver_updates_existing_resolution_row(session) -> None:
    entry = await _entry(session, symbol="BTC", region="crypto", asset_class="crypto")
    first = await resolve_watchlist_market_symbol(
        session,
        entry,
        settings=_settings(crypto_provider="binance"),
    )
    entry.symbol = "ETH"
    await session.flush()

    second = await resolve_watchlist_market_symbol(
        session,
        entry,
        settings=_settings(crypto_provider="binance"),
    )

    assert second.id == first.id
    assert second.symbol == "ETH"
    assert second.provider_symbol == "ETHUSDT"
    rows = list((await session.scalars(select(MarketSymbolResolution))).all())
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_watchlist_requests_reresolve_unresolved_rows(session) -> None:
    entry = await _entry(session, symbol="BTC", region="crypto", asset_class="crypto")
    session.add(
        MarketSymbolResolution(
            watchlist_entity_id=entry.id,
            symbol="BTC",
            asset_class="crypto",
            region="crypto",
            provider="coingecko",
            provider_symbol=None,
            status="unresolved",
            reason="temporary failure",
            resolution_metadata={"fallback_provider": "binance"},
            resolved_at=None,
        )
    )
    await session.flush()

    requests = await watchlist_market_symbol_requests(
        session,
        settings=_settings(crypto_provider="binance"),
    )

    assert len(requests) == 1
    assert requests[0].provider == "binance"
    assert requests[0].provider_symbol == "BTCUSDT"


@pytest.mark.asyncio
async def test_watchlist_requests_reresolve_when_cached_metadata_differs(session) -> None:
    entry = await _entry(session, symbol="ETH", region="crypto", asset_class="crypto")
    session.add(
        MarketSymbolResolution(
            watchlist_entity_id=entry.id,
            symbol="BTC",
            asset_class="crypto",
            region="crypto",
            provider="binance",
            provider_symbol="BTCUSDT",
            status="resolved",
            reason=None,
            resolution_metadata={"fallback_provider": "coingecko"},
            resolved_at=datetime.now(UTC),
        )
    )
    await session.flush()

    requests = await watchlist_market_symbol_requests(
        session,
        settings=_settings(crypto_provider="binance"),
    )

    assert len(requests) == 1
    assert requests[0].symbol == "ETH"
    assert requests[0].provider_symbol == "ETHUSDT"


@pytest.mark.asyncio
async def test_watchlist_requests_reresolve_stale_resolved_rows(session) -> None:
    entry = await _entry(session, symbol="BTC", region="crypto", asset_class="crypto")
    session.add(
        MarketSymbolResolution(
            watchlist_entity_id=entry.id,
            symbol="BTC",
            asset_class="crypto",
            region="crypto",
            provider="coingecko",
            provider_symbol="bitcoin",
            status="resolved",
            reason=None,
            resolution_metadata={"fallback_provider": "binance"},
            resolved_at=datetime.now(UTC) - timedelta(hours=25),
        )
    )
    await session.flush()

    requests = await watchlist_market_symbol_requests(
        session,
        settings=_settings(crypto_provider="binance"),
    )

    assert len(requests) == 1
    assert requests[0].provider == "binance"
    assert requests[0].provider_symbol == "BTCUSDT"


@pytest.mark.asyncio
async def test_resolver_threads_retry_policy_to_hyperliquid(session) -> None:
    class Client:
        async def request(self, method: str, url: str, **kwargs: object) -> httpx.Response:
            response = httpx.Response(200, json=[{"universe": [{"name": "xyz:NVDA"}]}, []])
            response.request = httpx.Request(method, url)
            return response

    entry = await _entry(session, symbol="NVDA", region="us", asset_class="us_equity")
    policy = ProviderRetryPolicy(max_retries=0, delays=())

    resolution = await resolve_watchlist_market_symbol(
        session,
        entry,
        settings=_settings(symbol_map={}),
        client=Client(),
        retry_policy=policy,
    )

    assert resolution.status == "resolved"


@pytest.mark.asyncio
async def test_watchlist_requests_fetch_hyperliquid_universe_once_per_batch(session) -> None:
    class Client:
        def __init__(self) -> None:
            self.calls = 0

        async def request(self, method: str, url: str, **kwargs: object) -> httpx.Response:
            self.calls += 1
            response = httpx.Response(
                200,
                json=[
                    {"universe": [{"name": "xyz:NVDA"}, {"name": "xyz:AAPL"}]},
                    [],
                ],
            )
            response.request = httpx.Request(method, url)
            return response

    client = Client()
    await _entry(session, symbol="NVDA", region="us", asset_class="us_equity")
    await _entry(session, symbol="AAPL", region="us", asset_class="us_equity")

    requests = await watchlist_market_symbol_requests(
        session,
        settings=_settings(symbol_map={}),
        client=client,
    )

    assert client.calls == 1
    assert {request.provider_symbol for request in requests} == {"xyz:NVDA", "xyz:AAPL"}
