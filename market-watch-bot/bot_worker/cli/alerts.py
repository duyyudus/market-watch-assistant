from __future__ import annotations

from typing import Annotated

import typer
from sqlalchemy import select

from bot_worker.cli.apps import alert_app, alert_policy_app
from bot_worker.cli.common import _echo_json, _run, _settings, _with_session
from bot_worker.db.models import (
    AlertDecisionRecord,
    EventCluster,
)
from bot_worker.scoring import AlertThresholds, decide_alert


@alert_policy_app.command("show")
def alert_policy_show() -> None:
    """Display the active alerting policy and scoring thresholds."""
    settings = _settings()
    _echo_json(
        {
            "immediate_threshold": settings.alerts.immediate_threshold,
            "watchlist_threshold": settings.alerts.watchlist_threshold,
            "digest_threshold": settings.alerts.digest_threshold,
            "default_channel": settings.alerts.default_channel,
        }
    )
@alert_policy_app.command("set")
def alert_policy_set(key: str, value: str) -> None:
    """Set an alerting policy parameter for this runtime (MVP placeholder)."""
    typer.echo(
        f"Policy setting {key}={value} accepted for runtime config; "
        "persistent edit is manual in MVP"
    )
@alert_policy_app.command("reset")
def alert_policy_reset() -> None:
    """Reset alerting policy to the defaults configured in settings.yml."""
    typer.echo("Alert policy reset uses defaults from settings.yml in MVP")
@alert_app.command("test")
def alert_test(score: Annotated[int, typer.Option("--score")] = 80) -> None:
    """Evaluate alerting decision (immediate, watchlist, or digest) for a hypothetical score."""
    settings = _settings()
    decision = decide_alert(
        score,
        AlertThresholds(
            immediate=settings.alerts.immediate_threshold,
            watchlist=settings.alerts.watchlist_threshold,
            digest=settings.alerts.digest_threshold,
        ),
    )
    _echo_json({"score": score, "decision": decision.decision, "reason": decision.reason})
@alert_app.command("list")
def alert_list(
    limit: Annotated[int, typer.Option("--limit", min=1, max=200)] = 20,
    level: Annotated[str | None, typer.Option("--level")] = None,
) -> None:
    """List recent alert decisions, optionally filtered by decision level."""
    async def action(session):
        stmt = (
            select(AlertDecisionRecord, EventCluster)
            .join(EventCluster, EventCluster.id == AlertDecisionRecord.event_cluster_id)
            .order_by(AlertDecisionRecord.created_at.desc())
            .limit(limit)
        )
        if level:
            stmt = stmt.where(AlertDecisionRecord.decision == level)
        rows = list((await session.execute(stmt)).all())
        if not rows:
            typer.echo("No alert decisions found")
            return
        for alert, event in rows:
            typer.echo(
                f"{alert.id}\t{alert.decision}\t{event.final_score}\t"
                f"{alert.channel or '-'}\t{event.canonical_headline}"
            )

    _run(_with_session(action))
@alert_app.command("show")
def alert_show(identifier: str) -> None:
    """Display detailed reasons and metadata for a specific alert decision."""
    async def action(session):
        stmt = (
            select(AlertDecisionRecord, EventCluster)
            .join(EventCluster, EventCluster.id == AlertDecisionRecord.event_cluster_id)
            .where(AlertDecisionRecord.id == identifier)
        )
        row = (await session.execute(stmt)).first()
        if row is None:
            typer.echo("Alert decision not found")
            raise typer.Exit(1)
        alert, event = row
        _echo_json(
            {
                "id": alert.id,
                "event_cluster_id": alert.event_cluster_id,
                "event": event.canonical_headline,
                "decision": alert.decision,
                "reason": alert.reason,
                "score": event.final_score,
                "score_breakdown": alert.score_breakdown,
                "channel": alert.channel,
                "suppression_reason": alert.suppression_reason,
                "created_at": alert.created_at,
            }
        )

    _run(_with_session(action))
