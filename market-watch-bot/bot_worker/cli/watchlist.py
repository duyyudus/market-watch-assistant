from __future__ import annotations

from typing import Annotated

import typer

from bot_worker.cli.apps import watchlist_app
from bot_worker.cli.common import _run, _with_session
from bot_worker.services import (
    add_watchlist_entry,
    watchlist_entries,
)
from bot_worker.watchlist import match_watchlist


@watchlist_app.command("add")
def watchlist_add(
    name: Annotated[str, typer.Option("--name")],
    symbol: Annotated[str | None, typer.Option("--symbol")] = None,
    entity_type: Annotated[str, typer.Option("--type")] = "macro_theme",
    region: Annotated[str | None, typer.Option("--region")] = None,
    asset_class: Annotated[str | None, typer.Option("--asset-class")] = None,
    tier: Annotated[str, typer.Option("--tier")] = "D",
    alias: Annotated[list[str] | None, typer.Option("--alias")] = None,
) -> None:
    """Add a symbol, entity, or theme to the active watchlist."""
    async def action(session):
        entry = await add_watchlist_entry(
            session,
            name=name,
            symbol=symbol,
            tier=tier,
            entity_type=entity_type,
            region=region,
            asset_class=asset_class,
            aliases=alias or [],
        )
        typer.echo(f"Added watchlist entry {entry.id}: {entry.name}")

    _run(_with_session(action))
@watchlist_app.command("list")
def watchlist_list() -> None:
    """List all items currently in the watchlist."""
    async def action(session):
        rows = await watchlist_entries(session)
        for row in rows:
            typer.echo(f"{row.symbol or '-'}\t{row.name}\t{row.tier}\t{row.entity_type}")

    _run(_with_session(action))
@watchlist_app.command("show")
def watchlist_show(identifier: str) -> None:
    """Show details of a specific watchlist entry (MVP placeholder)."""
    typer.echo(f"watchlist show {identifier} is deferred in MVP")
@watchlist_app.command("match")
def watchlist_match(text_value: str) -> None:
    """Test matching a text value against the watchlist entries."""
    async def action(session):
        matches = match_watchlist(text_value, await watchlist_entries(session))
        if not matches:
            typer.echo("No matches")
        for match in matches:
            typer.echo(f"{match.symbol or '-'}\t{match.name}\t{match.tier}\t{match.entity_type}")

    _run(_with_session(action))
