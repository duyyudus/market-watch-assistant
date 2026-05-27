from __future__ import annotations

import typer

from bot_worker.cli.apps import news_app


@news_app.command("list")
def news_list() -> None:
    """List ingested news items (MVP placeholder)."""
    typer.echo("news list requires database-backed normalized_news_items")
@news_app.command("show")
def news_show(identifier: str) -> None:
    """Display details of a specific news item (MVP placeholder)."""
    typer.echo(f"news show {identifier} requires database-backed normalized_news_items")
@news_app.command("search")
def news_search(query: str) -> None:
    """Search across ingested news items by title or content (MVP placeholder)."""
    typer.echo(f"news search for {query!r} uses title/snippet metadata in MVP")
