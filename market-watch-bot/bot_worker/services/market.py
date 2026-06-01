from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta

import httpx
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot_worker.catalysts import best_market_move_score_for_event
from bot_worker.db.models import (
    EventCluster,
    MarketMove,
    MissedCatalystReview,
)
from bot_worker.market_data import (
    MarketMoveDraft,
    parse_binance_ticker_move,
    parse_coingecko_market_move,
    parse_vietnam_quote_moves,
    parse_yahoo_chart_move,
    score_market_move,
)


@dataclass(frozen=True)
class MarketFetchResult:
    moves: list[MarketMoveDraft]
    degraded_providers: list[str] = field(default_factory=list)
    failed_providers: list[str] = field(default_factory=list)
    errors: dict[str, str] = field(default_factory=dict)


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
async def fetch_market_moves(
    *,
    symbols: list[str],
    window: str,
    vn_base_url: str,
    symbol_map: dict[str, str] | None = None,
    crypto_provider: str = "binance",
    crypto_fallback_provider: str = "coingecko",
) -> list[MarketMoveDraft]:
    result = await fetch_market_moves_with_stats(
        symbols=symbols,
        window=window,
        vn_base_url=vn_base_url,
        symbol_map=symbol_map,
        crypto_provider=crypto_provider,
        crypto_fallback_provider=crypto_fallback_provider,
    )
    return result.moves


async def fetch_market_moves_with_stats(
    *,
    symbols: list[str],
    window: str,
    vn_base_url: str,
    symbol_map: dict[str, str] | None = None,
    crypto_provider: str = "binance",
    crypto_fallback_provider: str = "coingecko",
    client: object | None = None,
) -> MarketFetchResult:
    symbol_map = symbol_map or {}
    global_symbol_set = {"SPY", "QQQ", "DIA", "GLD", "SLV", "USO", "DXY", "TNX"}
    crypto_symbols = [
        symbol.upper()
        for symbol in symbols
        if symbol.upper().endswith("USDT") or symbol.upper() in {"BTC", "ETH", "SOL"}
    ]
    global_symbols = [
        symbol.upper()
        for symbol in symbols
        if symbol.upper() in global_symbol_set or "." in symbol or symbol.upper().endswith(".US")
    ]
    routed = {*crypto_symbols, *global_symbols}
    vn_symbols = [symbol.lower() for symbol in symbols if symbol.upper() not in routed]
    moves: list[MarketMoveDraft] = []
    degraded: set[str] = set()
    failed: set[str] = set()
    errors: dict[str, str] = {}
    crypto_provider_order = list(
        dict.fromkeys(
            provider.lower()
            for provider in (crypto_provider, crypto_fallback_provider)
            if provider
        )
    )

    async def run(active_client: object) -> None:
        for symbol in crypto_symbols:
            fetched_crypto_move = False
            for index, provider in enumerate(crypto_provider_order):
                is_last_provider = index == len(crypto_provider_order) - 1
                try:
                    if provider == "binance":
                        binance_symbol = symbol if symbol.endswith("USDT") else f"{symbol}USDT"
                        response = await active_client.get(
                            "https://api.binance.com/api/v3/ticker/24hr",
                            params={"symbol": binance_symbol},
                        )
                        response.raise_for_status()
                        moves.append(parse_binance_ticker_move(response.json(), window=window))
                        fetched_crypto_move = True
                        break
                    if provider == "coingecko":
                        coin_id = symbol_map.get(symbol.removesuffix("USDT"), symbol.lower())
                        response = await active_client.get(
                            "https://api.coingecko.com/api/v3/coins/markets",
                            params={
                                "vs_currency": "usd",
                                "ids": coin_id,
                                "price_change_percentage": "24h",
                            },
                        )
                        response.raise_for_status()
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
            if not crypto_provider_order and not fetched_crypto_move:
                failed.add("crypto_market")
                errors.setdefault(
                    "crypto_market",
                    "No crypto market data providers configured",
                )
        for symbol in global_symbols:
            yahoo_symbol = symbol_map.get(symbol, symbol)
            try:
                response = await active_client.get(
                    f"https://query2.finance.yahoo.com/v8/finance/chart/{yahoo_symbol}",
                    params={"range": "5d", "interval": "1d"},
                    headers={"User-Agent": "Mozilla/5.0"},
                )
                response.raise_for_status()
                moves.append(
                    parse_yahoo_chart_move(
                        response.json(),
                        symbol=symbol,
                        asset_class="equity",
                        window=window,
                    )
                )
            except Exception as exc:  # noqa: BLE001
                failed.add("yahoo_finance")
                errors.setdefault("yahoo_finance", str(exc))
        if vn_symbols:
            try:
                response = await active_client.post(
                    f"{vn_base_url.rstrip('/')}/api/v1/stocks/quotes",
                    json={"symbols": vn_symbols},
                    headers={"accept": "application/json"},
                )
                response.raise_for_status()
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
                EventCluster.created_at >= move.timestamp - timedelta(hours=24),
                EventCluster.created_at <= move.timestamp + timedelta(hours=24),
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
async def market_move_score_for_cluster(session: AsyncSession, cluster: EventCluster) -> int:
    rows = list(
        (
            await session.scalars(
                select(MarketMove).where(
                    MarketMove.timestamp >= cluster.created_at - timedelta(hours=24),
                    MarketMove.timestamp <= cluster.created_at + timedelta(hours=24),
                )
            )
        ).all()
    )
    moves = [
        MarketMoveDraft(
            asset_symbol=row.asset_symbol,
            asset_class=row.asset_class,
            exchange=row.exchange,
            timestamp=row.timestamp,
            window=row.window,
            price_change_pct=row.price_change_pct,
            volume_change_pct=row.volume_change_pct,
            value_traded_change_pct=row.value_traded_change_pct,
            z_score=row.z_score,
        )
        for row in rows
    ]
    return best_market_move_score_for_event(
        affected_tickers=cluster.affected_tickers,
        affected_entities=cluster.affected_entities,
        event_time=cluster.created_at,
        moves=moves,
        tolerance=timedelta(hours=24),
    )
