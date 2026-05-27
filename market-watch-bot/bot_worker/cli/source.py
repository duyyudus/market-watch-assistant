from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from bot_worker.cli.apps import source_app
from bot_worker.cli.common import _db_error, _echo_json, _run, _with_session
from bot_worker.services import (
    add_source,
    fetch_source,
    get_source,
    import_sources_yaml,
    list_sources,
    purge_source,
    set_source_enabled,
)


@source_app.command("add")
def source_add(
    kind: Annotated[str, typer.Argument(help="Source type, usually rss")] = "rss",
    name: Annotated[str, typer.Option("--name")] = "",
    url: Annotated[str, typer.Option("--url")] = "",
    region: Annotated[str, typer.Option("--region")] = "global",
    category: Annotated[str, typer.Option("--category")] = "global_macro",
    language: Annotated[str, typer.Option("--language")] = "en",
    score: Annotated[int, typer.Option("--score")] = 60,
    interval: Annotated[int, typer.Option("--interval")] = 300,
) -> None:
    """Add a new data source (e.g., RSS feed) to the database."""
    async def action(session):
        source = await add_source(
            session,
            name=name,
            url=url,
            region=region,
            category=category,
            source_type=kind,
            language=language,
            score=score,
            interval=interval,
        )
        typer.echo(f"Added source {source.id}: {source.name}")

    try:
        _run(_with_session(action))
    except Exception as exc:  # noqa: BLE001
        _db_error(exc)
        raise typer.Exit(1) from exc
@source_app.command("list")
def source_list(enabled: Annotated[bool, typer.Option("--enabled")] = False) -> None:
    """List all ingestion sources, optionally filtering by enabled status."""
    async def action(session):
        rows = await list_sources(session, enabled=True if enabled else None)
        if not rows:
            typer.echo("No sources found")
        for source in rows:
            state = "enabled" if source.enabled else "disabled"
            typer.echo(f"{source.id}\t{source.name}\t{source.region}\t{source.category}\t{state}")

    try:
        _run(_with_session(action))
    except Exception as exc:  # noqa: BLE001
        _db_error(exc)
@source_app.command("show")
def source_show(identifier: str) -> None:
    """Show the details and current configuration of a specific source."""
    async def action(session):
        source = await get_source(session, identifier)
        if source is None:
            typer.echo("Source not found")
            raise typer.Exit(1)
        _echo_json(
            {
                "id": source.id,
                "name": source.name,
                "url": source.url,
                "region": source.region,
                "category": source.category,
                "enabled": source.enabled,
                "score": source.source_score,
            }
        )

    _run(_with_session(action))
@source_app.command("test")
def source_test(identifier: str) -> None:
    """Test fetching and parsing a source without saving the items to the database."""
    async def action(session):
        source = await get_source(session, identifier)
        if source is None:
            typer.echo("Source not found")
            raise typer.Exit(1)
        result = await fetch_source(session, source)
        _echo_json(result)

    _run(_with_session(action))
@source_app.command("fetch")
def source_fetch(identifier: str) -> None:
    """Fetch and test a source (alias for 'source test')."""
    source_test(identifier)
@source_app.command("enable")
def source_enable(identifier: str) -> None:
    """Enable a specific data source by its identifier."""
    async def action(session):
        ok = await set_source_enabled(session, identifier, True)
        typer.echo("enabled" if ok else "source not found")

    _run(_with_session(action))
@source_app.command("disable")
def source_disable(identifier: str) -> None:
    """Disable a specific data source by its identifier."""
    async def action(session):
        ok = await set_source_enabled(session, identifier, False)
        typer.echo("disabled" if ok else "source not found")

    _run(_with_session(action))
@source_app.command("purge")
def source_purge(
    identifier: str,
    yes: Annotated[
        bool, typer.Option("--yes", help="Confirm permanent deletion of the source and its data")
    ] = False,
) -> None:
    """Permanently delete a source and all its associated news items and events."""
    if not yes:
        typer.echo("Refusing to purge without --yes")
        raise typer.Exit(1)

    async def action(session):
        result = await purge_source(session, identifier)
        if result.get("status") == "not_found":
            typer.echo("source not found")
            raise typer.Exit(1)
        typer.echo(f"Purged source {result['source']}")
        for key, value in result.items():
            if key in {"status", "source"}:
                continue
            typer.echo(f"{key}: {value}")

    _run(_with_session(action))
@source_app.command("import")
def source_import(path: Path) -> None:
    """Import multiple data sources from a YAML configuration file."""
    sources = import_sources_yaml(path)

    async def action(session):
        count = 0
        for source in sources:
            await add_source(
                session,
                name=str(source["name"]),
                url=str(source["url"]),
                region=str(source.get("region", "global")),
                category=str(source.get("category", "global_macro")),
                source_type=str(source.get("type", "rss")),
                language=str(source.get("language", "en")),
                score=int(source.get("score", 60)),
                interval=int(source.get("interval", 300)),
            )
            count += 1
        typer.echo(f"Imported {count} sources")

    _run(_with_session(action))
@source_app.command("export")
def source_export(out: Annotated[Path, typer.Option("--out")] = Path("sources.yaml")) -> None:
    """Export all defined data sources to a YAML file."""
    async def action(session):
        rows = await list_sources(session)
        data = {
            "sources": [
                {
                    "name": source.name,
                    "url": source.url,
                    "region": source.region,
                    "category": source.category,
                    "type": source.source_type,
                    "language": source.language,
                    "score": source.source_score,
                    "interval": source.polling_interval_seconds,
                }
                for source in rows
            ]
        }
        import yaml

        out.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
        typer.echo(f"Exported {len(rows)} sources to {out}")

    _run(_with_session(action))
