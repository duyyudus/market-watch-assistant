from __future__ import annotations

from typing import Annotated

import typer

from bot_worker.cli.apps import event_app
from bot_worker.cli.common import _run, _with_session
from bot_worker.services import (
    digest_preview,
)


@event_app.command("list")
def event_list() -> None:
    """List active event clusters sorted by final score."""
    async def action(session):
        rows = await digest_preview(session)
        for event in rows:
            typer.echo(
                f"{event.id}\t{event.final_score}\t{event.status}\t{event.canonical_headline}"
            )

    _run(_with_session(action))
@event_app.command("show")
def event_show(identifier: str) -> None:
    """Show details of a specific event cluster (MVP placeholder)."""
    typer.echo(f"event show {identifier} requires event_clusters data")
@event_app.command("merge")
def event_merge(left: str, right: str) -> None:
    """Manually merge two event clusters (MVP placeholder)."""
    typer.echo(f"event merge requested for {left} and {right}; manual merge is deferred in MVP")
@event_app.command("rescore")
def event_rescore(identifier: str) -> None:
    """Trigger manual rescoring of an event cluster (MVP placeholder)."""
    typer.echo(f"event rescore requested for {identifier}; scoring runs during pipeline in MVP")
@event_app.command("mark")
def event_mark(identifier: str, status: Annotated[str, typer.Option("--status")]) -> None:
    """Change status or category of an event cluster (MVP placeholder)."""
    typer.echo(f"event mark requested for {identifier}: {status}; direct update is deferred in MVP")
