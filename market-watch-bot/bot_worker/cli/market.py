from __future__ import annotations

from typing import Annotated

import typer

from bot_worker.cli.apps import market_app
from bot_worker.cli.common import _echo_json, _run, _settings, _with_session
from bot_worker.services import (
    fetch_market_moves,
    store_market_moves,
)


@market_app.command("fetch")
def market_fetch(
    symbols: Annotated[str, typer.Option("--symbols")],
    window: Annotated[str, typer.Option("--window")] = "1d",
) -> None:
    """Fetch recent market moves for watchlisted assets and store them in the database."""
    settings = _settings()
    parsed_symbols = [symbol.strip() for symbol in symbols.split(",") if symbol.strip()]

    async def action(session):
        moves = await fetch_market_moves(
            symbols=parsed_symbols,
            window=window,
            vn_base_url=settings.market_data.vn_base_url,
            symbol_map=settings.market_data.symbol_map,
        )
        inserted = await store_market_moves(session, moves)
        _echo_json(
            {
                "inserted": inserted,
                "symbols": parsed_symbols,
            }
        )

    _run(_with_session(action))
