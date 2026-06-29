from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from bot_worker.catalysts import (
    MARKET_MOVE_POST_EVENT_WINDOW,
    MARKET_MOVE_PRE_EVENT_WINDOW,
    best_market_move_score_for_event,
)
from bot_worker.db.models import (
    EventCluster,
    MarketMove,
    MissedCatalystReview,
)
from bot_worker.market_data import (
    GLOBAL_ASSET_CLASSES,
    HYPERLIQUID_SYMBOL_PREFIX,
    MarketMoveDraft,
    MarketSymbolRequest,
    market_move_draft_from_row,
    parse_binance_ticker_move,
    parse_coingecko_market_move,
    parse_hyperliquid_market_moves,
    parse_vietnam_quote_moves,
    score_market_move,
)
from bot_worker.services.external_providers import request_with_retry
from common.market import MarketResolvedSymbolRequest

COINGECKO_MISSING_API_KEY_ERROR = "COINGECKO_API_KEY is required for CoinGecko market data"
MISSED_CATALYST_ACTION_TTL = timedelta(hours=24)


@dataclass(frozen=True)
class MarketFetchResult:
    moves: list[MarketMoveDraft]
    degraded_providers: list[str] = field(default_factory=list)
    failed_providers: list[str] = field(default_factory=list)
    errors: dict[str, str] = field(default_factory=dict)
    skipped_symbols: dict[str, str] = field(default_factory=dict)
    unavailable_symbols: dict[str, str] = field(default_factory=dict)


async def store_market_moves(session: AsyncSession, moves: list[MarketMoveDraft]) -> int:
    for move in moves:
        session.add(
            MarketMove(
                asset_symbol=move.asset_symbol,
                asset_class=move.asset_class,
                exchange=move.exchange,
                timestamp=move.timestamp,
                window=move.window,
                price_change_pct=move.price_change_pct,
                volume_change_pct=move.volume_change_pct,
                value_traded_change_pct=move.value_traded_change_pct,
                z_score=move.z_score,
            )
        )
    return len(moves)


async def expire_stale_missed_catalyst_reviews(
    session: AsyncSession,
    *,
    now: datetime | None = None,
) -> int:
    cutoff = (now or datetime.now(UTC)) - MISSED_CATALYST_ACTION_TTL
    result = await session.execute(
        update(MissedCatalystReview)
        .where(MissedCatalystReview.detected_event_cluster_id.is_(None))
        .where(MissedCatalystReview.status.in_(("pending", "investigating")))
        .where(MissedCatalystReview.created_at < cutoff)
        .values(status="expired")
    )
    return result.rowcount or 0


async def fetch_market_moves(
    *,
    symbols: list[str],
    window: str,
    vn_base_url: str,
    symbol_map: dict[str, str] | None = None,
    crypto_provider: str = "binance",
    crypto_fallback_provider: str = "coingecko",
    coingecko_api_key: str | None = None,
    global_provider: str = "hyperliquid",
    hyperliquid_base_url: str = "https://api.hyperliquid.xyz",
    hyperliquid_dex: str = "xyz",
    hyperliquid_min_day_notional_volume: float = 100000,
) -> list[MarketMoveDraft]:
    result = await fetch_market_moves_with_stats(
        symbols=symbols,
        window=window,
        vn_base_url=vn_base_url,
        symbol_map=symbol_map,
        crypto_provider=crypto_provider,
        crypto_fallback_provider=crypto_fallback_provider,
        coingecko_api_key=coingecko_api_key,
        global_provider=global_provider,
        hyperliquid_base_url=hyperliquid_base_url,
        hyperliquid_dex=hyperliquid_dex,
        hyperliquid_min_day_notional_volume=hyperliquid_min_day_notional_volume,
    )
    return result.moves


def _normalized_symbol_map(symbol_map: dict[str, str]) -> dict[str, str]:
    return {key.upper(): value for key, value in symbol_map.items()}


def _legacy_request(symbol: str, symbol_map: dict[str, str]) -> MarketSymbolRequest:
    normalized = symbol.upper()
    mapped = symbol_map.get(normalized)
    if normalized.endswith("USDT") or normalized in {"BTC", "ETH", "SOL"}:
        return MarketSymbolRequest(symbol=normalized, asset_class="crypto", region="crypto")
    if mapped and mapped.upper().startswith(HYPERLIQUID_SYMBOL_PREFIX):
        return MarketSymbolRequest(symbol=normalized, asset_class="equity", region="global")
    if mapped:
        return MarketSymbolRequest(symbol=normalized, asset_class="crypto", region="crypto")
    return MarketSymbolRequest(symbol=normalized)


def _coingecko_headers(api_key: str | None) -> dict[str, str]:
    if not api_key:
        raise ValueError(COINGECKO_MISSING_API_KEY_ERROR)
    return {"x-cg-demo-api-key": api_key}


def _route_market_symbols(
    requests: list[MarketSymbolRequest],
    symbol_map: dict[str, str],
) -> tuple[
    list[MarketSymbolRequest],
    dict[str, list[MarketSymbolRequest]],
    list[MarketSymbolRequest],
    list[MarketSymbolRequest],
]:
    crypto: list[MarketSymbolRequest] = []
    hyperliquid: dict[str, list[MarketSymbolRequest]] = {}
    vietnam: list[MarketSymbolRequest] = []
    unrouted: list[MarketSymbolRequest] = []
    for request in requests:
        symbol = request.symbol.upper()
        asset_class = (request.asset_class or "").lower()
        region = (request.region or "").lower()
        if asset_class == "crypto" or region == "crypto":
            crypto.append(MarketSymbolRequest(symbol=symbol, asset_class="crypto", region=region))
            continue
        if asset_class == "vietnam_equity" or region == "vietnam":
            vietnam.append(request)
            continue
        mapped_symbol = symbol_map.get(symbol)
        if mapped_symbol and (
            mapped_symbol.upper().startswith(HYPERLIQUID_SYMBOL_PREFIX)
            or asset_class in GLOBAL_ASSET_CLASSES
            or region in {"global", "us"}
        ):
            hyperliquid.setdefault(mapped_symbol, []).append(
                MarketSymbolRequest(
                    symbol=symbol,
                    asset_class=request.asset_class,
                    region=request.region,
                )
            )
            continue
        unrouted.append(request)
    return crypto, hyperliquid, vietnam, unrouted


def _route_resolved_symbols(
    requests: list[MarketResolvedSymbolRequest],
) -> tuple[
    list[MarketResolvedSymbolRequest],
    dict[str, list[MarketSymbolRequest]],
    list[MarketResolvedSymbolRequest],
    dict[str, str],
    dict[str, str],
]:
    crypto: list[MarketResolvedSymbolRequest] = []
    hyperliquid: dict[str, list[MarketSymbolRequest]] = {}
    vietnam: list[MarketResolvedSymbolRequest] = []
    skipped: dict[str, str] = {}
    unavailable: dict[str, str] = {}

    for request in requests:
        symbol = request.symbol.upper()
        if request.status == "skipped":
            skipped[symbol] = request.reason or "Market data resolution skipped"
            continue
        if request.status != "resolved" or not request.provider_symbol:
            unavailable[symbol] = request.reason or f"No market data resolution for {symbol}"
            continue
        provider = (request.provider or "").lower()
        if provider in {"binance", "coingecko"}:
            crypto.append(request)
            continue
        if provider == "hyperliquid":
            hyperliquid.setdefault(request.provider_symbol, []).append(
                MarketSymbolRequest(
                    symbol=symbol,
                    asset_class=request.asset_class,
                    region=request.region,
                )
            )
            continue
        if provider == "vietnam_market":
            vietnam.append(request)
            continue
        unavailable[symbol] = f"Unsupported resolved market data provider: {provider or 'unknown'}"
    return crypto, hyperliquid, vietnam, skipped, unavailable


async def fetch_market_moves_with_stats(
    *,
    symbols: list[str] | None = None,
    market_symbols: list[MarketSymbolRequest] | None = None,
    resolved_symbols: list[MarketResolvedSymbolRequest] | None = None,
    window: str,
    vn_base_url: str,
    symbol_map: dict[str, str] | None = None,
    crypto_provider: str = "binance",
    crypto_fallback_provider: str = "coingecko",
    coingecko_api_key: str | None = None,
    global_provider: str = "hyperliquid",
    hyperliquid_base_url: str = "https://api.hyperliquid.xyz",
    hyperliquid_dex: str = "xyz",
    hyperliquid_min_day_notional_volume: float = 100000,
    client: object | None = None,
) -> MarketFetchResult:
    normalized_map = _normalized_symbol_map(symbol_map or {})
    requests = market_symbols or [
        _legacy_request(symbol, normalized_map) for symbol in symbols or []
    ]
    crypto_symbols, hyperliquid_symbols, vn_requests, unrouted = _route_market_symbols(
        requests,
        normalized_map,
    )
    vn_symbols = [request.symbol.lower() for request in vn_requests]
    moves: list[MarketMoveDraft] = []
    degraded: set[str] = set()
    failed: set[str] = set()
    errors: dict[str, str] = {}
    skipped: dict[str, str] = {}
    unavailable: dict[str, str] = {}
    resolved_crypto_symbols: list[MarketResolvedSymbolRequest] = []
    resolved_hyperliquid_symbols: dict[str, list[MarketSymbolRequest]] = {}
    resolved_vn_symbols: list[MarketResolvedSymbolRequest] = []
    if resolved_symbols:
        (
            resolved_crypto_symbols,
            resolved_hyperliquid_symbols,
            resolved_vn_symbols,
            resolved_skipped,
            resolved_unavailable,
        ) = _route_resolved_symbols(resolved_symbols)
        skipped.update(resolved_skipped)
        unavailable.update(resolved_unavailable)
        crypto_symbols = []
        hyperliquid_symbols = {}
        vn_requests = []
        unrouted = []
    crypto_provider_order = list(
        dict.fromkeys(
            provider.lower()
            for provider in (crypto_provider, crypto_fallback_provider)
            if provider
        )
    )

    async def run(active_client: object) -> None:
        crypto_requests = [
            *resolved_crypto_symbols,
            *[
                MarketResolvedSymbolRequest(
                    symbol=request.symbol,
                    asset_class=request.asset_class,
                    region=request.region,
                    provider=None,
                    provider_symbol=None,
                )
                for request in crypto_symbols
            ],
        ]
        for request in crypto_requests:
            symbol = request.symbol.upper()
            provider_order = (
                list(
                    dict.fromkeys(
                        provider.lower()
                        for provider in (request.provider, request.fallback_provider)
                        if provider
                    )
                )
                if request.provider
                else crypto_provider_order
            )
            fetched_crypto_move = False
            for index, provider in enumerate(provider_order):
                is_last_provider = index == len(provider_order) - 1
                try:
                    if provider == "binance":
                        if request.provider == "binance" and request.provider_symbol:
                            binance_symbol = request.provider_symbol
                        else:
                            binance_symbol = symbol if symbol.endswith("USDT") else f"{symbol}USDT"
                        response = await request_with_retry(
                            provider="binance",
                            method="GET",
                            url="https://api.binance.com/api/v3/ticker/24hr",
                            client=active_client,
                            params={"symbol": binance_symbol},
                        )
                        moves.append(parse_binance_ticker_move(response.json(), window=window))
                        fetched_crypto_move = True
                        break
                    if provider == "coingecko":
                        if request.provider == "coingecko" and request.provider_symbol:
                            coin_id = request.provider_symbol
                        else:
                            coin_id = normalized_map.get(
                                symbol.removesuffix("USDT"),
                                symbol.lower(),
                            )
                        response = await request_with_retry(
                            provider="coingecko",
                            method="GET",
                            url="https://api.coingecko.com/api/v3/coins/markets",
                            client=active_client,
                            headers=_coingecko_headers(coingecko_api_key),
                            params={
                                "vs_currency": "usd",
                                "ids": coin_id,
                                "price_change_percentage": "24h",
                            },
                        )
                        moves.append(
                            parse_coingecko_market_move(
                                response.json(),
                                symbol=symbol,
                                window=window,
                            )
                        )
                        fetched_crypto_move = True
                        break
                    raise ValueError(f"Unsupported crypto market data provider: {provider}")
                except Exception as exc:  # noqa: BLE001 - provider boundary catches parser/transport errors
                    if is_last_provider:
                        failed.add(provider)
                    else:
                        degraded.add(provider)
                    errors.setdefault(provider, str(exc))
            if not provider_order and not fetched_crypto_move:
                failed.add("crypto_market")
                errors.setdefault(
                    "crypto_market",
                    "No crypto market data providers configured",
                )
        for request in unrouted:
            unavailable[request.symbol.upper()] = (
                f"No market data route for {request.symbol.upper()}"
            )
        combined_hyperliquid_symbols = {**resolved_hyperliquid_symbols, **hyperliquid_symbols}
        if combined_hyperliquid_symbols:
            provider = global_provider.lower()
            if provider != "hyperliquid":
                failed.add(provider)
                errors.setdefault(provider, f"Unsupported global market data provider: {provider}")
            elif window != "1d":
                failed.add("hyperliquid")
                errors.setdefault("hyperliquid", "Hyperliquid provider only supports window='1d'")
            else:
                try:
                    response = await request_with_retry(
                        provider="hyperliquid",
                        method="POST",
                        url=f"{hyperliquid_base_url.rstrip('/')}/info",
                        client=active_client,
                        json={"type": "metaAndAssetCtxs", "dex": hyperliquid_dex},
                        headers={"Content-Type": "application/json"},
                    )
                    (
                        hyperliquid_moves,
                        hyperliquid_skipped,
                        hyperliquid_unavailable,
                    ) = parse_hyperliquid_market_moves(
                        response.json(),
                        requests_by_coin=combined_hyperliquid_symbols,
                        window=window,
                        min_day_notional_volume=hyperliquid_min_day_notional_volume,
                    )
                    moves.extend(hyperliquid_moves)
                    skipped.update(hyperliquid_skipped)
                    unavailable.update(hyperliquid_unavailable)
                except Exception as exc:  # noqa: BLE001
                    failed.add("hyperliquid")
                    errors.setdefault("hyperliquid", str(exc))
        resolved_vn_provider_symbols = [request.provider_symbol for request in resolved_vn_symbols]
        all_vn_symbols = [*resolved_vn_provider_symbols, *vn_symbols]
        if all_vn_symbols:
            try:
                response = await request_with_retry(
                    provider="vietnam_market",
                    method="POST",
                    url=f"{vn_base_url.rstrip('/')}/api/v1/stocks/quotes",
                    client=active_client,
                    json={"symbols": all_vn_symbols},
                    headers={"accept": "application/json"},
                )
                moves.extend(parse_vietnam_quote_moves(response.json()))
            except Exception as exc:  # noqa: BLE001
                failed.add("vietnam_market")
                errors.setdefault("vietnam_market", str(exc))

    if client is not None:
        await run(client)
    else:
        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as active_client:
            await run(active_client)
    return MarketFetchResult(
        moves=moves,
        degraded_providers=sorted(degraded),
        failed_providers=sorted(failed),
        errors=errors,
        skipped_symbols=skipped,
        unavailable_symbols=unavailable,
    )
async def run_missed_catalyst_review(session: AsyncSession, *, window: str = "1d") -> int:
    existing_reviews = select(MissedCatalystReview.asset_symbol).where(
        MissedCatalystReview.move_window == window
    )
    moves = list(
        (
            await session.scalars(
                select(MarketMove)
                .where(MarketMove.window == window)
                .where(MarketMove.asset_symbol.not_in(existing_reviews))
            )
        ).all()
    )
    count = 0
    for move in moves:
        move_score = score_market_move(
            price_change_pct=move.price_change_pct,
            volume_change_pct=move.volume_change_pct,
            z_score=move.z_score,
        )
        if move_score < 70:
            continue
        matched = await session.scalar(
            select(EventCluster).where(
                EventCluster.created_at >= move.timestamp - MARKET_MOVE_POST_EVENT_WINDOW,
                EventCluster.created_at <= move.timestamp + MARKET_MOVE_PRE_EVENT_WINDOW,
                or_(
                    EventCluster.affected_tickers.contains([move.asset_symbol]),
                    EventCluster.affected_entities.contains([move.asset_symbol]),
                ),
            )
        )
        session.add(
            MissedCatalystReview(
                asset_symbol=move.asset_symbol,
                asset_class=move.asset_class,
                move_window=move.window,
                price_change_pct=move.price_change_pct,
                volume_change_pct=move.volume_change_pct,
                detected_event_cluster_id=matched.id if matched else None,
                status="resolved" if matched else "pending",
            )
        )
        count += 1
    return count
async def market_move_score_for_cluster(session: AsyncSession, cluster: EventCluster) -> int | None:
    symbols = sorted(
        {
            value
            for value in [*(cluster.affected_tickers or []), *(cluster.affected_entities or [])]
            if value
        }
    )
    if not symbols:
        return 0
    rows = list(
        (
            await session.scalars(
                select(MarketMove).where(
                    MarketMove.asset_symbol.in_(symbols),
                    MarketMove.timestamp >= cluster.created_at - MARKET_MOVE_PRE_EVENT_WINDOW,
                    MarketMove.timestamp <= cluster.created_at + MARKET_MOVE_POST_EVENT_WINDOW,
                )
            )
        ).all()
    )
    moves = [market_move_draft_from_row(row) for row in rows]
    if not moves:
        return None
    return best_market_move_score_for_event(
        affected_tickers=cluster.affected_tickers,
        affected_entities=cluster.affected_entities,
        event_time=cluster.created_at,
        moves=moves,
        pre_event_window=MARKET_MOVE_PRE_EVENT_WINDOW,
        post_event_window=MARKET_MOVE_POST_EVENT_WINDOW,
    )
