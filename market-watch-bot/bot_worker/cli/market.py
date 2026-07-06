from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated

import typer
from sqlalchemy import or_, select

from bot_worker.cli.apps import market_app
from bot_worker.cli.common import _echo_json, _run, _settings, _with_session
from bot_worker.db.models import EventCluster, MarketMove
from bot_worker.services import (
    fetch_market_moves,
    fetch_market_moves_with_stats,
    store_market_moves,
    watchlist_market_symbol_requests,
)


def _since_cutoff(value: str) -> datetime:
    now = datetime.now(UTC)
    stripped = value.strip().lower()
    if stripped.endswith("d") and stripped[:-1].isdigit():
        return now - timedelta(days=int(stripped[:-1]))
    if stripped.endswith("h") and stripped[:-1].isdigit():
        return now - timedelta(hours=int(stripped[:-1]))
    return datetime.fromisoformat(value).astimezone(UTC)


def _move_payload(move: MarketMove) -> dict[str, object]:
    return {
        "id": move.id,
        "asset_symbol": move.asset_symbol,
        "asset_class": move.asset_class,
        "exchange": move.exchange,
        "timestamp": move.timestamp,
        "window": move.window,
        "price_change_pct": move.price_change_pct,
        "volume_change_pct": move.volume_change_pct,
        "value_traded_change_pct": move.value_traded_change_pct,
        "z_score": move.z_score,
        "created_at": move.created_at,
    }


def _move_draft_payload(move) -> dict[str, object]:
    return {
        "asset_symbol": move.asset_symbol,
        "asset_class": getattr(move, "asset_class", None),
        "exchange": getattr(move, "exchange", None),
        "timestamp": getattr(move, "timestamp", None),
        "window": getattr(move, "window", None),
        "price_change_pct": move.price_change_pct,
        "volume_change_pct": getattr(move, "volume_change_pct", None),
        "value_traded_change_pct": getattr(move, "value_traded_change_pct", None),
        "z_score": getattr(move, "z_score", None),
    }


@market_app.command("fetch")
def market_fetch(
    symbols: Annotated[str | None, typer.Option("--symbols")] = None,
    window: Annotated[str, typer.Option("--window")] = "1d",
) -> None:
    """Fetch recent market moves and store them in the database."""
    settings = _settings()
    requested_symbols = (
        [symbol.strip() for symbol in symbols.split(",") if symbol.strip()] if symbols else []
    )

    async def action(session):
        if requested_symbols:
            mode = "symbols"
            moves = await fetch_market_moves(
                symbols=requested_symbols,
                window=window,
                vnstock_base_url=settings.market_data.vnstock_base_url,
                symbol_map=settings.market_data.symbol_map,
                crypto_provider=settings.market_data.crypto_provider,
                crypto_fallback_provider=settings.market_data.crypto_fallback_provider,
                coingecko_api_key=settings.coingecko_api_key,
                global_provider=settings.market_data.global_provider,
                hyperliquid_base_url=settings.market_data.hyperliquid_base_url,
                hyperliquid_dex=settings.market_data.hyperliquid_dex,
                hyperliquid_min_day_notional_volume=(
                    settings.market_data.hyperliquid_min_day_notional_volume
                ),
            )
            skipped_symbols = {}
            unavailable_symbols = {}
            degraded_providers = []
            failed_providers = []
            errors = {}
            output_symbols = requested_symbols
        else:
            mode = "watchlist"
            resolved_symbols = await watchlist_market_symbol_requests(session, settings=settings)
            output_symbols = sorted({request.symbol for request in resolved_symbols})
            market_result = await fetch_market_moves_with_stats(
                resolved_symbols=resolved_symbols,
                window=window,
                vnstock_base_url=settings.market_data.vnstock_base_url,
                symbol_map=settings.market_data.symbol_map,
                crypto_provider=settings.market_data.crypto_provider,
                crypto_fallback_provider=settings.market_data.crypto_fallback_provider,
                coingecko_api_key=settings.coingecko_api_key,
                global_provider=settings.market_data.global_provider,
                hyperliquid_base_url=settings.market_data.hyperliquid_base_url,
                hyperliquid_dex=settings.market_data.hyperliquid_dex,
                hyperliquid_min_day_notional_volume=(
                    settings.market_data.hyperliquid_min_day_notional_volume
                ),
            )
            moves = market_result.moves
            skipped_symbols = market_result.skipped_symbols
            unavailable_symbols = market_result.unavailable_symbols
            degraded_providers = market_result.degraded_providers
            failed_providers = market_result.failed_providers
            errors = market_result.errors
        inserted = await store_market_moves(session, moves)
        _echo_json(
            {
                "mode": mode,
                "inserted": inserted,
                "symbols": output_symbols,
                "moves": [_move_draft_payload(move) for move in moves],
                "skipped_symbols": skipped_symbols,
                "unavailable_symbols": unavailable_symbols,
                "degraded_providers": degraded_providers,
                "failed_providers": failed_providers,
                "errors": errors,
            }
        )

    _run(_with_session(action))


@market_app.command("move")
def market_move(identifier: str) -> None:
    """Show a stored market move."""
    async def action(session):
        move = await session.get(MarketMove, identifier)
        if move is None:
            typer.echo("Market move not found")
            raise typer.Exit(1)
        _echo_json(_move_payload(move))

    _run(_with_session(action))


@market_app.command("movers")
def market_movers(
    asset_class: Annotated[str | None, typer.Option("--asset-class")] = None,
    since: Annotated[str, typer.Option("--since")] = "24h",
    min_change: Annotated[float | None, typer.Option("--min-change")] = None,
    limit: Annotated[int, typer.Option("--limit", min=1, max=200)] = 20,
) -> None:
    """List stored market movers."""
    async def action(session):
        stmt = (
            select(MarketMove)
            .where(MarketMove.timestamp >= _since_cutoff(since))
            .order_by(MarketMove.timestamp.desc())
            .limit(limit)
        )
        if asset_class:
            stmt = stmt.where(MarketMove.asset_class == asset_class)
        if min_change is not None:
            stmt = stmt.where(
                or_(
                    MarketMove.price_change_pct >= min_change,
                    MarketMove.price_change_pct <= -min_change,
                )
            )
        rows = list((await session.execute(stmt)).scalars().all())
        if not rows:
            typer.echo("No market moves found")
            return
        for move in rows:
            typer.echo(
                f"{move.id}\t{move.asset_symbol}\t{move.asset_class}\t"
                f"{move.window}\t{move.price_change_pct}\t{move.z_score or '-'}"
            )

    _run(_with_session(action))


@market_app.command("join")
def market_join(
    since: Annotated[str, typer.Option("--since")] = "24h",
    limit: Annotated[int, typer.Option("--limit", min=1, max=200)] = 20,
) -> None:
    """Show recent event clusters and nearby stored market moves."""
    async def action(session):
        events = list(
            (
                await session.scalars(
                    select(EventCluster)
                    .where(EventCluster.created_at >= _since_cutoff(since))
                    .order_by(EventCluster.created_at.desc())
                    .limit(limit)
                )
            ).all()
        )
        payload = []
        for event in events:
            moves = list(
                (
                    await session.scalars(
                        select(MarketMove).where(
                            MarketMove.timestamp >= event.created_at - timedelta(hours=24),
                            MarketMove.timestamp <= event.created_at + timedelta(hours=24),
                            or_(
                                MarketMove.asset_symbol.in_(event.affected_tickers or [""]),
                                MarketMove.asset_symbol.in_(event.affected_entities or [""]),
                            ),
                        )
                    )
                ).all()
            )
            payload.append(
                {
                    "event_cluster_id": event.id,
                    "headline": event.canonical_headline,
                    "final_score": event.final_score,
                    "moves": [_move_payload(move) for move in moves],
                }
            )
        _echo_json(payload)

    _run(_with_session(action))
