from __future__ import annotations

from typing import Annotated

import typer
from sqlalchemy import select

from bot_worker.cli.apps import catalyst_app
from bot_worker.cli.common import _echo_json, _run, _with_session
from bot_worker.db.models import MissedCatalystReview
from bot_worker.services import (
    run_missed_catalyst_review,
)


@catalyst_app.command("review")
def catalyst_review(window: Annotated[str, typer.Option("--window")] = "1d") -> None:
    """Run automated review of missed catalysts over a specified window."""
    async def action(session):
        count = await run_missed_catalyst_review(session, window=window)
        _echo_json({"created": count, "window": window})

    _run(_with_session(action))


def _review_payload(review: MissedCatalystReview) -> dict[str, object]:
    return {
        "id": review.id,
        "asset_symbol": review.asset_symbol,
        "asset_class": review.asset_class,
        "move_window": review.move_window,
        "price_change_pct": review.price_change_pct,
        "volume_change_pct": review.volume_change_pct,
        "detected_event_cluster_id": review.detected_event_cluster_id,
        "status": review.status,
        "agent_summary": review.agent_summary,
        "created_at": review.created_at,
        "updated_at": review.updated_at,
    }


@catalyst_app.command("list")
def catalyst_list(
    status: Annotated[str | None, typer.Option("--status")] = None,
    limit: Annotated[int, typer.Option("--limit", min=1, max=200)] = 20,
) -> None:
    """List missed catalyst review records."""
    async def action(session):
        stmt = select(MissedCatalystReview).order_by(MissedCatalystReview.created_at.desc()).limit(
            limit
        )
        if status:
            stmt = stmt.where(MissedCatalystReview.status == status)
        rows = list((await session.scalars(stmt)).all())
        if not rows:
            typer.echo("No catalyst reviews found")
            return
        for review in rows:
            typer.echo(
                f"{review.id}\t{review.status}\t{review.asset_symbol}\t"
                f"{review.move_window}\t{review.price_change_pct}"
            )

    _run(_with_session(action))


@catalyst_app.command("show")
def catalyst_show(identifier: str) -> None:
    """Show a missed catalyst review."""
    async def action(session):
        review = await session.get(MissedCatalystReview, identifier)
        if review is None:
            typer.echo("Catalyst review not found")
            raise typer.Exit(1)
        _echo_json(_review_payload(review))

    _run(_with_session(action))


@catalyst_app.command("resolve")
def catalyst_resolve(
    identifier: str,
    status: Annotated[str, typer.Option("--status")],
    event_id: Annotated[str | None, typer.Option("--event")] = None,
    summary: Annotated[str | None, typer.Option("--summary")] = None,
) -> None:
    """Resolve or update a missed catalyst review status."""
    allowed = {"resolved", "no_clear_catalyst", "false_signal", "ignored", "expired"}
    if status not in allowed:
        typer.echo(f"status must be one of: {', '.join(sorted(allowed))}")
        raise typer.Exit(1)

    async def action(session):
        review = await session.get(MissedCatalystReview, identifier)
        if review is None:
            typer.echo("Catalyst review not found")
            raise typer.Exit(1)
        review.status = status
        if event_id is not None:
            review.detected_event_cluster_id = event_id
        if summary is not None:
            review.agent_summary = summary
        _echo_json(_review_payload(review))

    _run(_with_session(action))
