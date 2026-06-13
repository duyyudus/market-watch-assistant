from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from common.config import Settings, load_settings
from common.db.models import MarketSymbolResolution, WatchlistEntity
from common.external_providers import ProviderRetryPolicy, request_with_retry
from common.market import (
    GLOBAL_ASSET_CLASSES,
    HYPERLIQUID_SYMBOL_PREFIX,
    MarketResolvedSymbolRequest,
)

RESOLUTION_TTL = timedelta(hours=24)
RESOLUTION_TRIGGER_FIELDS = frozenset({"symbol", "asset_class", "region", "enabled"})


def _normalize_symbol(symbol: str | None) -> str | None:
    if symbol is None:
        return None
    normalized = symbol.strip().upper()
    return normalized or None


def _normalize_optional(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().lower()
    return normalized or None


def _normalized_symbol_map(settings: Settings) -> dict[str, str]:
    return {key.upper(): value for key, value in settings.market_data.symbol_map.items()}


def _fallback_provider(settings: Settings) -> str | None:
    value = settings.market_data.crypto_fallback_provider
    return value.lower() if value else None


def watchlist_resolution_fields_changed(fields: set[str]) -> bool:
    return bool(RESOLUTION_TRIGGER_FIELDS & fields)


def _resolution_payload(
    entry: WatchlistEntity,
    *,
    status: str,
    provider: str | None,
    provider_symbol: str | None,
    reason: str | None,
    resolution_metadata: dict[str, object] | None = None,
) -> dict[str, object | None]:
    return {
        "symbol": _normalize_symbol(entry.symbol),
        "asset_class": _normalize_optional(entry.asset_class),
        "region": _normalize_optional(entry.region),
        "provider": provider,
        "provider_symbol": provider_symbol,
        "status": status,
        "reason": reason,
        "resolution_metadata": resolution_metadata or {},
        "resolved_at": datetime.now(UTC) if status == "resolved" else None,
    }


async def _upsert_resolution(
    session: AsyncSession,
    entry: WatchlistEntity,
    payload: dict[str, object | None],
) -> MarketSymbolResolution:
    resolution = await session.scalar(
        select(MarketSymbolResolution).where(
            MarketSymbolResolution.watchlist_entity_id == entry.id
        )
    )
    if resolution is None:
        resolution = MarketSymbolResolution(
            watchlist_entity_id=entry.id,
            **payload,
        )
        session.add(resolution)
    else:
        for key, value in payload.items():
            setattr(resolution, key, value)
    await session.flush()
    return resolution


def _hyperliquid_candidates(symbol: str) -> set[str]:
    normalized = symbol.upper()
    return {normalized, f"{HYPERLIQUID_SYMBOL_PREFIX}{normalized}"}


def _instrument_aliases(name: str) -> set[str]:
    normalized = name.upper()
    aliases = {normalized}
    if normalized.startswith(HYPERLIQUID_SYMBOL_PREFIX):
        aliases.add(normalized.removeprefix(HYPERLIQUID_SYMBOL_PREFIX))
    return aliases


async def _hyperliquid_universe_names(
    *,
    settings: Settings,
    client: object | None,
    retry_policy: ProviderRetryPolicy | None = None,
) -> list[str]:
    async def request(active_client: object) -> list[str]:
        response = await request_with_retry(
            provider="hyperliquid",
            method="POST",
            url=f"{settings.market_data.hyperliquid_base_url.rstrip('/')}/info",
            client=active_client,
            retry_policy=retry_policy,
            json={"type": "metaAndAssetCtxs", "dex": settings.market_data.hyperliquid_dex},
            headers={"Content-Type": "application/json"},
        )
        payload = response.json()
        if not isinstance(payload, list) or not payload:
            raise ValueError("Hyperliquid response missing metadata")
        meta = payload[0]
        if not isinstance(meta, dict) or not isinstance(meta.get("universe"), list):
            raise ValueError("Hyperliquid response missing universe")
        names: list[str] = []
        for instrument in meta["universe"]:
            if isinstance(instrument, dict) and instrument.get("name"):
                names.append(str(instrument["name"]))
        return names

    if client is not None:
        return await request(client)
    async with httpx.AsyncClient(timeout=20, follow_redirects=True) as active_client:
        return await request(active_client)


async def _resolve_hyperliquid(
    *,
    symbol: str,
    settings: Settings,
    client: object | None,
    retry_policy: ProviderRetryPolicy | None = None,
    universe_names: list[str] | None = None,
) -> tuple[str, str | None, dict[str, object]]:
    mapped = _normalized_symbol_map(settings).get(symbol)
    if mapped and mapped.upper().startswith(HYPERLIQUID_SYMBOL_PREFIX):
        return "resolved", mapped, {"match_source": "symbol_map"}
    if universe_names is None:
        universe_names = await _hyperliquid_universe_names(
            settings=settings,
            client=client,
            retry_policy=retry_policy,
        )
    candidates = _hyperliquid_candidates(symbol)
    for name in universe_names:
        if candidates & _instrument_aliases(name):
            return "resolved", name, {"match_source": "hyperliquid_universe"}
    return "unresolved", None, {"match_source": "hyperliquid_universe"}


async def resolve_watchlist_market_symbol(
    session: AsyncSession,
    entry: WatchlistEntity,
    *,
    settings: Settings | None = None,
    client: object | None = None,
    retry_policy: ProviderRetryPolicy | None = None,
    hyperliquid_universe_names: list[str] | None = None,
) -> MarketSymbolResolution:
    active_settings = settings or load_settings()
    symbol = _normalize_symbol(entry.symbol)
    region = _normalize_optional(entry.region)
    asset_class = _normalize_optional(entry.asset_class)

    if symbol is None:
        return await _upsert_resolution(
            session,
            entry,
            _resolution_payload(
                entry,
                status="skipped",
                provider=None,
                provider_symbol=None,
                reason="watchlist entry has no symbol",
            ),
        )

    if region == "vietnam" or asset_class == "vietnam_equity":
        return await _upsert_resolution(
            session,
            entry,
            _resolution_payload(
                entry,
                status="resolved",
                provider="vietnam_market",
                provider_symbol=symbol.lower(),
                reason=None,
            ),
        )

    if region == "crypto" or asset_class == "crypto":
        provider = active_settings.market_data.crypto_provider.lower()
        if provider == "binance":
            provider_symbol = symbol if symbol.endswith("USDT") else f"{symbol}USDT"
            return await _upsert_resolution(
                session,
                entry,
                _resolution_payload(
                    entry,
                    status="resolved",
                    provider="binance",
                    provider_symbol=provider_symbol,
                    reason=None,
                    resolution_metadata={"fallback_provider": _fallback_provider(active_settings)},
                ),
            )
        if provider == "coingecko":
            coin_id = _normalized_symbol_map(active_settings).get(symbol.removesuffix("USDT"))
            if coin_id:
                return await _upsert_resolution(
                    session,
                    entry,
                    _resolution_payload(
                        entry,
                        status="resolved",
                        provider="coingecko",
                        provider_symbol=coin_id,
                        reason=None,
                        resolution_metadata={
                            "fallback_provider": _fallback_provider(active_settings)
                        },
                    ),
                )
            return await _upsert_resolution(
                session,
                entry,
                _resolution_payload(
                    entry,
                    status="unresolved",
                    provider="coingecko",
                    provider_symbol=None,
                    reason=f"CoinGecko coin id is not configured for {symbol}",
                    resolution_metadata={
                        "fallback_provider": _fallback_provider(active_settings)
                    },
                ),
            )
        return await _upsert_resolution(
            session,
            entry,
            _resolution_payload(
                entry,
                status="unresolved",
                provider=provider,
                provider_symbol=None,
                reason=f"Unsupported crypto market data provider: {provider}",
            ),
        )

    if asset_class in GLOBAL_ASSET_CLASSES and region in {"global", "us"}:
        provider = active_settings.market_data.global_provider.lower()
        if provider != "hyperliquid":
            return await _upsert_resolution(
                session,
                entry,
                _resolution_payload(
                    entry,
                    status="unresolved",
                    provider=provider,
                    provider_symbol=None,
                    reason=f"Unsupported global market data provider: {provider}",
                ),
            )
        try:
            status, provider_symbol, metadata = await _resolve_hyperliquid(
                symbol=symbol,
                settings=active_settings,
                client=client,
                retry_policy=retry_policy,
                universe_names=hyperliquid_universe_names,
            )
            return await _upsert_resolution(
                session,
                entry,
                _resolution_payload(
                    entry,
                    status=status,
                    provider="hyperliquid",
                    provider_symbol=provider_symbol,
                    reason=None
                    if status == "resolved"
                    else f"No Hyperliquid instrument matched {symbol}",
                    resolution_metadata=metadata,
                ),
            )
        except Exception as exc:  # noqa: BLE001 - provider boundary stores diagnostics
            return await _upsert_resolution(
                session,
                entry,
                _resolution_payload(
                    entry,
                    status="unresolved",
                    provider="hyperliquid",
                    provider_symbol=None,
                    reason=str(exc),
                    resolution_metadata={"error_type": type(exc).__name__},
                ),
            )

    return await _upsert_resolution(
        session,
        entry,
        _resolution_payload(
            entry,
            status="unresolved",
            provider=None,
            provider_symbol=None,
            reason=(
                f"No resolver for region={region or 'unknown'} "
                f"asset_class={asset_class or 'unknown'}"
            ),
        ),
    )


def resolution_to_market_request(
    resolution: MarketSymbolResolution,
) -> MarketResolvedSymbolRequest:
    metadata = resolution.resolution_metadata or {}
    fallback_provider = metadata.get("fallback_provider")
    return MarketResolvedSymbolRequest(
        symbol=resolution.symbol or "",
        asset_class=resolution.asset_class,
        region=resolution.region,
        provider=resolution.provider,
        provider_symbol=resolution.provider_symbol,
        fallback_provider=str(fallback_provider) if fallback_provider else None,
        status=resolution.status,
        reason=resolution.reason,
    )


def _resolution_matches_entry(
    resolution: MarketSymbolResolution,
    entry: WatchlistEntity,
) -> bool:
    return (
        resolution.symbol == _normalize_symbol(entry.symbol)
        and resolution.asset_class == _normalize_optional(entry.asset_class)
        and resolution.region == _normalize_optional(entry.region)
    )


def _resolution_is_stale(
    resolution: MarketSymbolResolution,
    *,
    now: datetime,
) -> bool:
    if resolution.status != "resolved":
        return True
    if resolution.resolved_at is None:
        return True
    resolved_at = resolution.resolved_at
    if resolved_at.tzinfo is None:
        resolved_at = resolved_at.replace(tzinfo=UTC)
    return resolved_at <= now - RESOLUTION_TTL


def _needs_hyperliquid_universe(entry: WatchlistEntity, settings: Settings) -> bool:
    symbol = _normalize_symbol(entry.symbol)
    if symbol is None:
        return False
    asset_class = _normalize_optional(entry.asset_class)
    region = _normalize_optional(entry.region)
    if asset_class not in GLOBAL_ASSET_CLASSES or region not in {"global", "us"}:
        return False
    if settings.market_data.global_provider.lower() != "hyperliquid":
        return False
    mapped = _normalized_symbol_map(settings).get(symbol)
    return not (mapped and mapped.upper().startswith(HYPERLIQUID_SYMBOL_PREFIX))


async def watchlist_market_symbol_requests(
    session: AsyncSession,
    *,
    settings: Settings | None = None,
    client: object | None = None,
) -> list[MarketResolvedSymbolRequest]:
    if not hasattr(session, "scalars"):
        return []
    active_settings = settings or load_settings()
    entries = list(
        (
            await session.scalars(
                select(WatchlistEntity).where(WatchlistEntity.enabled.is_(True))
            )
        ).all()
    )
    if not entries:
        return []
    resolutions = list(
        (
            await session.scalars(
                select(MarketSymbolResolution).where(
                    MarketSymbolResolution.watchlist_entity_id.in_(
                        [entry.id for entry in entries]
                    )
                )
            )
        ).all()
    )
    by_entry_id = {resolution.watchlist_entity_id: resolution for resolution in resolutions}
    requests: list[MarketResolvedSymbolRequest] = []
    now = datetime.now(UTC)
    hyperliquid_universe_names: list[str] | None = None
    for entry in entries:
        resolution = by_entry_id.get(entry.id)
        should_resolve = (
            resolution is None
            or not _resolution_matches_entry(resolution, entry)
            or _resolution_is_stale(resolution, now=now)
        )
        if (
            should_resolve
            and _needs_hyperliquid_universe(entry, active_settings)
            and hyperliquid_universe_names is None
        ):
            hyperliquid_universe_names = await _hyperliquid_universe_names(
                settings=active_settings,
                client=client,
            )
        if should_resolve:
            resolution = await resolve_watchlist_market_symbol(
                session,
                entry,
                settings=active_settings,
                client=client,
                hyperliquid_universe_names=hyperliquid_universe_names,
            )
        if resolution.symbol:
            requests.append(resolution_to_market_request(resolution))
    return requests
