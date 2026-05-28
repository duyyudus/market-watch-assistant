from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
import yaml
from sqlalchemy import select

from bot_worker.cli.apps import watchlist_app
from bot_worker.cli.common import _echo_json, _run, _with_session
from bot_worker.db.models import WatchlistEntity
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
    """Show details of a specific watchlist entry."""
    async def action(session):
        entry = await session.get(WatchlistEntity, identifier)
        if entry is None:
            typer.echo("Watchlist entry not found")
            raise typer.Exit(1)
        _echo_json(_entry_payload(entry))

    _run(_with_session(action))


def _entry_payload(entry: WatchlistEntity) -> dict[str, object]:
    return {
        "id": entry.id,
        "symbol": entry.symbol,
        "name": entry.name,
        "entity_type": entry.entity_type,
        "tier": entry.tier,
        "region": entry.region,
        "asset_class": entry.asset_class,
        "aliases": entry.aliases,
        "enabled": entry.enabled,
        "created_at": entry.created_at,
        "updated_at": entry.updated_at,
    }


@watchlist_app.command("update")
def watchlist_update(
    identifier: str,
    name: Annotated[str | None, typer.Option("--name")] = None,
    symbol: Annotated[str | None, typer.Option("--symbol")] = None,
    entity_type: Annotated[str | None, typer.Option("--type")] = None,
    region: Annotated[str | None, typer.Option("--region")] = None,
    asset_class: Annotated[str | None, typer.Option("--asset-class")] = None,
    tier: Annotated[str | None, typer.Option("--tier")] = None,
    alias: Annotated[list[str] | None, typer.Option("--alias")] = None,
    enabled: Annotated[bool | None, typer.Option("--enabled/--disabled")] = None,
) -> None:
    """Update mutable fields on a watchlist entry."""
    async def action(session):
        entry = await session.get(WatchlistEntity, identifier)
        if entry is None:
            typer.echo("Watchlist entry not found")
            raise typer.Exit(1)
        if name is not None:
            entry.name = name
        if symbol is not None:
            entry.symbol = symbol
        if entity_type is not None:
            entry.entity_type = entity_type
        if region is not None:
            entry.region = region
        if asset_class is not None:
            entry.asset_class = asset_class
        if tier is not None:
            entry.tier = tier
        if alias is not None:
            entry.aliases = alias
        if enabled is not None:
            entry.enabled = enabled
        _echo_json(_entry_payload(entry))

    _run(_with_session(action))


@watchlist_app.command("remove")
def watchlist_remove(
    identifier: str,
    yes: Annotated[bool, typer.Option("--yes")] = False,
) -> None:
    """Remove a watchlist entry."""
    if not yes:
        typer.echo("Refusing to remove without --yes")
        raise typer.Exit(1)

    async def action(session):
        entry = await session.get(WatchlistEntity, identifier)
        if entry is None:
            typer.echo("Watchlist entry not found")
            raise typer.Exit(1)
        await session.delete(entry)
        typer.echo(f"Removed watchlist entry {identifier}")

    _run(_with_session(action))


@watchlist_app.command("import")
def watchlist_import(path: Path) -> None:
    """Import watchlist entries from a YAML file."""
    with path.open(encoding="utf-8") as handle:
        rows = yaml.safe_load(handle) or []
    if isinstance(rows, dict):
        rows = rows.get("watchlist", [])
    if not isinstance(rows, list):
        typer.echo("Watchlist YAML must be a list or contain a watchlist list")
        raise typer.Exit(1)

    async def action(session):
        count = 0
        for row in rows:
            if not isinstance(row, dict) or not row.get("name"):
                continue
            session.add(
                WatchlistEntity(
                    name=str(row["name"]),
                    symbol=row.get("symbol"),
                    entity_type=str(row.get("entity_type", row.get("type", "macro_theme"))),
                    tier=str(row.get("tier", "D")),
                    region=row.get("region"),
                    asset_class=row.get("asset_class"),
                    aliases=list(row.get("aliases", [])),
                    enabled=bool(row.get("enabled", True)),
                )
            )
            count += 1
        _echo_json({"imported": count})

    _run(_with_session(action))


@watchlist_app.command("export")
def watchlist_export(out: Annotated[str, typer.Option("--out")] = "watchlist.yaml") -> None:
    """Export watchlist entries to a YAML file."""
    async def action(session):
        rows = list((await session.scalars(select(WatchlistEntity))).all())
        payload = {"watchlist": [_entry_payload(row) for row in rows]}
        with open(out, "w", encoding="utf-8") as handle:
            yaml.safe_dump(payload, handle, sort_keys=False)
        typer.echo(f"Exported {len(rows)} watchlist entries to {out}")

    _run(_with_session(action))


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
