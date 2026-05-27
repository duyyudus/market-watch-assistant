from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated
from zoneinfo import ZoneInfo

import typer

from bot_worker.cli.apps import digest_app
from bot_worker.cli.common import _run, _settings, _with_session
from bot_worker.digest import digest_window_for_date
from bot_worker.services import (
    digest_display_headline,
    digest_preview,
)


@digest_app.command("preview")
def digest_preview_command(limit: Annotated[int, typer.Option("--limit")] = 20) -> None:
    """Preview event clusters compiled for the current digest window."""
    async def action(session):
        rows = await digest_preview(session, limit=limit)
        if not rows:
            typer.echo("No digest events")
        for event in rows:
            section = event.regions[0] if event.regions else "global"
            typer.echo(f"[{section}] {event.final_score} {event.canonical_headline}")

    _run(_with_session(action))
@digest_app.command("build")
def digest_build(
    date_value: Annotated[str | None, typer.Option("--date")] = None,
    since_value: Annotated[str | None, typer.Option("--since")] = None,
    until_value: Annotated[str | None, typer.Option("--until")] = None,
    limit: Annotated[int, typer.Option("--limit")] = 50,
) -> None:
    """Build and format digest for a specific day or date range."""
    settings = _settings()
    if date_value:
        since, until = digest_window_for_date(date_value, ZoneInfo(settings.bot.timezone))
    else:
        since = datetime.fromisoformat(since_value).astimezone(UTC) if since_value else None
        until = datetime.fromisoformat(until_value).astimezone(UTC) if until_value else None

    async def action(session):
        rows = await digest_preview(session, limit=limit, since=since, until=until)
        if not rows:
            typer.echo("No digest events")
        for event in rows:
            section = event.regions[0] if event.regions else "global"
            headline = await digest_display_headline(session, event, since=since, until=until)
            typer.echo(f"[{section}] {event.final_score} {event.status} {headline}")

    _run(_with_session(action))
@digest_app.command("history")
def digest_history() -> None:
    """Browse historical digest runs (MVP placeholder)."""
    typer.echo("digest history is represented by event and alert history in MVP")
