from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated

import typer

from bot_worker.cli.apps import event_app
from bot_worker.cli.common import _echo_json, _run, _with_session
from bot_worker.services import (
    digest_preview,
    event_report_time_range,
    format_report_time_range,
    recluster_recent_event_clusters,
)


@event_app.command("list")
def event_list() -> None:
    """List active event clusters sorted by final score."""
    async def action(session):
        rows = await digest_preview(session)
        for event in rows:
            report_time = format_report_time_range(await event_report_time_range(session, event.id))
            time_suffix = f"\t{report_time}" if report_time else ""
            typer.echo(
                f"{event.id}\t{event.final_score}\t{event.status}{time_suffix}"
                f"\t{event.canonical_headline}"
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


def _since_cutoff(value: str) -> datetime:
    now = datetime.now(UTC)
    stripped = value.strip().lower()
    if stripped.endswith("d") and stripped[:-1].isdigit():
        return now - timedelta(days=int(stripped[:-1]))
    if stripped.endswith("h") and stripped[:-1].isdigit():
        return now - timedelta(hours=int(stripped[:-1]))
    return datetime.fromisoformat(value).astimezone(UTC)


@event_app.command("recluster")
def event_recluster(
    since_value: Annotated[str, typer.Option("--since")] = "48h",
    apply: Annotated[bool, typer.Option("--apply")] = False,
    confirm: Annotated[bool, typer.Option("--confirm")] = False,
    limit: Annotated[int, typer.Option("--limit")] = 500,
) -> None:
    """Recluster recent event items; dry-run by default."""
    if apply and not confirm:
        typer.echo("Use --confirm with --apply to mutate event clusters.")
        raise typer.Exit(1)
    since = _since_cutoff(since_value)

    async def action(session):
        result = await recluster_recent_event_clusters(
            session,
            since=since,
            dry_run=not apply,
            limit=limit,
        )
        _echo_json(result)

    _run(_with_session(action))
@event_app.command("rescore")
def event_rescore(identifier: str) -> None:
    """Trigger manual rescoring of an event cluster (MVP placeholder)."""
    typer.echo(f"event rescore requested for {identifier}; scoring runs during pipeline in MVP")
@event_app.command("mark")
def event_mark(identifier: str, status: Annotated[str, typer.Option("--status")]) -> None:
    """Change status or category of an event cluster (MVP placeholder)."""
    typer.echo(f"event mark requested for {identifier}: {status}; direct update is deferred in MVP")
