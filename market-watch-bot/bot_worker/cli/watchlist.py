from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
import yaml
from sqlalchemy import func, select

from bot_worker.cli.apps import watchlist_app
from bot_worker.cli.common import _echo_json, _run, _with_session
from bot_worker.db.models import MarketSymbolResolution, WatchlistEntity
from bot_worker.services import (
    add_watchlist_entry,
    resolve_watchlist_market_symbol,
    watchlist_entries,
)
from common.market_symbol_resolver import watchlist_resolution_fields_changed
from bot_worker.watchlist import match_watchlist


@watchlist_app.command("add")
def watchlist_add(
    name: Annotated[str, typer.Option("--name")],
    symbol: Annotated[str | None, typer.Option("--symbol")] = None,
    entity_type: Annotated[str, typer.Option("--type")] = "macro_theme",
    region: Annotated[str, typer.Option("--region")] = ...,
    asset_class: Annotated[str, typer.Option("--asset-class")] = ...,
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
        resolution = await resolve_watchlist_market_symbol(session, entry)
        typer.echo(f"Added watchlist entry {entry.id}: {entry.name}")
        typer.echo(f"market data: {_resolution_summary(resolution)}")

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
        resolution = await _entry_resolution(session, entry)
        _echo_json(_entry_payload(entry, resolution))

    _run(_with_session(action))


async def _entry_resolution(session, entry: WatchlistEntity) -> MarketSymbolResolution | None:
    if not hasattr(session, "scalar"):
        return None
    return await session.scalar(
        select(MarketSymbolResolution).where(
            MarketSymbolResolution.watchlist_entity_id == entry.id
        )
    )


def _resolution_payload(
    resolution: MarketSymbolResolution | None,
) -> dict[str, object | None] | None:
    if resolution is None:
        return None
    return {
        "status": resolution.status,
        "provider": resolution.provider,
        "provider_symbol": resolution.provider_symbol,
        "reason": resolution.reason,
        "resolved_at": resolution.resolved_at,
    }


def _resolution_summary(resolution: MarketSymbolResolution | None) -> str:
    if resolution is None:
        return "unknown"
    parts = [resolution.status]
    if resolution.provider:
        parts.append(resolution.provider)
    if resolution.provider_symbol:
        parts.append(resolution.provider_symbol)
    if resolution.reason:
        parts.append(f"({resolution.reason})")
    return " ".join(parts)


def _display_symbol(symbol: str | None) -> str:
    return symbol or "-"


def _entry_payload(
    entry: WatchlistEntity,
    resolution: MarketSymbolResolution | None = None,
) -> dict[str, object]:
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
        "market_data_resolution": _resolution_payload(resolution),
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
        changed_fields = {
            name
            for name, value in {
                "symbol": symbol,
                "region": region,
                "asset_class": asset_class,
                "enabled": enabled,
            }.items()
            if value is not None
        }
        if watchlist_resolution_fields_changed(changed_fields):
            resolution = await resolve_watchlist_market_symbol(session, entry)
        else:
            resolution = await _entry_resolution(session, entry)
        _echo_json(_entry_payload(entry, resolution))

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


@watchlist_app.command("reset")
def watchlist_reset(
    yes: Annotated[bool, typer.Option("--yes")] = False,
) -> None:
    """Remove all watchlist entries."""
    if not yes:
        typer.echo("Refusing to reset watchlist without --yes")
        raise typer.Exit(1)

    async def action(session):
        rows = list((await session.scalars(select(WatchlistEntity))).all())
        for entry in rows:
            await session.delete(entry)
        typer.echo(f"Removed {len(rows)} watchlist entries")

    _run(_with_session(action))


@watchlist_app.command("import")
def watchlist_import(
    path: Annotated[Path, typer.Argument()] = Path("starter-watchlist.yml"),
) -> None:
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
        skipped = 0
        resolution_counts = {"resolved": 0, "unresolved": 0, "resolution_skipped": 0}
        typer.echo(f"Importing watchlist from {path}")
        for index, row in enumerate(rows, start=1):
            if not isinstance(row, dict) or not row.get("name"):
                typer.echo(f"Skipped row {index}: missing name or invalid row")
                continue
            raw_symbol = row.get("symbol")
            symbol = str(raw_symbol).strip().upper() if raw_symbol else None
            name = str(row["name"]).strip()
            if not row.get("region") or not row.get("asset_class"):
                skipped += 1
                typer.echo(f"Skipped row {index}: missing region or asset_class")
                continue
            existing = None
            existing_match = None
            if symbol:
                existing = await session.scalar(
                    select(WatchlistEntity).where(func.upper(WatchlistEntity.symbol) == symbol)
                )
                if existing is not None:
                    existing_match = "symbol"
            if not existing:
                existing = await session.scalar(
                    select(WatchlistEntity).where(func.lower(WatchlistEntity.name) == name.lower())
                )
                if existing is not None:
                    existing_match = "name"
            if existing is not None:
                skipped += 1
                typer.echo(
                    f"Skipped {name} ({_display_symbol(symbol)}): "
                    f"existing watchlist entry matched {existing_match or 'entry'}"
                )
                continue
            entry = WatchlistEntity(
                name=name,
                symbol=symbol,
                entity_type=str(row.get("entity_type", row.get("type", "macro_theme"))),
                tier=str(row.get("tier", "D")),
                region=str(row["region"]).strip().lower(),
                asset_class=str(row["asset_class"]).strip().lower(),
                aliases=list(row.get("aliases", [])),
                enabled=bool(row.get("enabled", True)),
            )
            session.add(entry)
            if hasattr(session, "flush"):
                await session.flush()
            resolution = await resolve_watchlist_market_symbol(session, entry)
            if resolution.status == "skipped":
                resolution_counts["resolution_skipped"] += 1
            elif resolution.status in resolution_counts:
                resolution_counts[resolution.status] += 1
            typer.echo(
                f"Imported {entry.name} ({_display_symbol(entry.symbol)}): "
                f"market data {_resolution_summary(resolution)}"
            )
            if resolution.status == "unresolved":
                typer.echo(
                    f"Unresolved {entry.name} ({_display_symbol(entry.symbol)}): "
                    f"{resolution.reason or 'no market data route resolved'}"
                )
            elif resolution.status == "skipped":
                typer.echo(
                    f"Resolution skipped {entry.name} ({_display_symbol(entry.symbol)}): "
                    f"{resolution.reason or 'market data resolution skipped'}"
                )
            count += 1
        _echo_json({"imported": count, "skipped": skipped, **resolution_counts})

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
