from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated

import typer
from sqlalchemy import select

from bot_worker.cli.apps import event_app
from bot_worker.cli.common import _echo_json, _run, _with_session
from bot_worker.db.models import (
    AgentInvestigation,
    AlertDecisionRecord,
    EventCluster,
    EventScoreHistory,
)
from bot_worker.scoring import ScoreInput, score_event
from bot_worker.services import (
    digest_preview,
    event_report_time_range,
    format_report_time_range,
    market_move_score_for_cluster,
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
    """Show details of a specific event cluster."""
    async def action(session):
        event = await session.get(EventCluster, identifier)
        if event is None:
            typer.echo("Event cluster not found")
            raise typer.Exit(1)
        latest_alert = await session.scalar(
            select(AlertDecisionRecord)
            .where(AlertDecisionRecord.event_cluster_id == event.id)
            .order_by(AlertDecisionRecord.created_at.desc())
            .limit(1)
        )
        latest_investigation = await session.scalar(
            select(AgentInvestigation)
            .where(AgentInvestigation.target_type == "event_cluster")
            .where(AgentInvestigation.target_id == event.id)
            .order_by(AgentInvestigation.created_at.desc())
            .limit(1)
        )
        report_time = format_report_time_range(await event_report_time_range(session, event.id))
        _echo_json(
            {
                "id": event.id,
                "headline": event.canonical_headline,
                "summary": event.summary,
                "status": event.status,
                "regions": event.regions,
                "asset_classes": event.asset_classes,
                "affected_entities": event.affected_entities,
                "affected_tickers": event.affected_tickers,
                "source_count": event.source_count,
                "top_source_score": event.top_source_score,
                "confirmation_score": event.confirmation_score,
                "novelty_score": event.novelty_score,
                "urgency_score": event.urgency_score,
                "market_impact_score": event.market_impact_score,
                "relevance_score": event.relevance_score,
                "final_score": event.final_score,
                "alert_level": event.alert_level,
                "first_seen_at": event.first_seen_at,
                "last_updated_at": event.last_updated_at,
                "report_time": report_time,
                "latest_alert": (
                    {
                        "id": latest_alert.id,
                        "decision": latest_alert.decision,
                        "reason": latest_alert.reason,
                        "channel": latest_alert.channel,
                        "sent_at": latest_alert.sent_at,
                        "created_at": latest_alert.created_at,
                        "score_breakdown": latest_alert.score_breakdown,
                    }
                    if latest_alert is not None
                    else None
                ),
                "latest_investigation": (
                    {
                        "id": latest_investigation.id,
                        "status": latest_investigation.status,
                        "trigger_reason": latest_investigation.trigger_reason,
                        "result": latest_investigation.result,
                        "error": latest_investigation.error_message,
                        "created_at": latest_investigation.created_at,
                        "updated_at": latest_investigation.updated_at,
                    }
                    if latest_investigation is not None
                    else None
                ),
            }
        )

    _run(_with_session(action))
@event_app.command("merge")
def event_merge(
    left: str,
    right: str,
    confirm: Annotated[bool, typer.Option("--confirm")] = False,
) -> None:
    """Manually mark two event clusters as merged."""
    if not confirm:
        typer.echo("Use --confirm to merge event clusters.")
        raise typer.Exit(1)

    async def action(session):
        left_event = await session.get(EventCluster, left)
        right_event = await session.get(EventCluster, right)
        if left_event is None or right_event is None:
            typer.echo("Event cluster not found")
            raise typer.Exit(1)
        left_event.source_count = max(
            left_event.source_count,
            left_event.source_count + right_event.source_count,
        )
        left_event.top_source_score = max(left_event.top_source_score, right_event.top_source_score)
        left_event.confirmation_score = max(
            left_event.confirmation_score, right_event.confirmation_score
        )
        left_event.market_impact_score = max(
            left_event.market_impact_score, right_event.market_impact_score
        )
        left_event.relevance_score = max(left_event.relevance_score, right_event.relevance_score)
        left_event.final_score = max(left_event.final_score, right_event.final_score)
        left_event.regions = sorted({*left_event.regions, *right_event.regions})
        left_event.asset_classes = sorted({*left_event.asset_classes, *right_event.asset_classes})
        left_event.affected_entities = sorted(
            {*left_event.affected_entities, *right_event.affected_entities}
        )
        left_event.affected_tickers = sorted(
            {*left_event.affected_tickers, *right_event.affected_tickers}
        )
        right_event.status = "merged"
        right_event.summary = f"Merged into {left_event.id}"
        _echo_json(
            {
                "merged_into": left_event.id,
                "merged_from": right_event.id,
                "status": right_event.status,
                "final_score": left_event.final_score,
            }
        )

    _run(_with_session(action))


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
    """Trigger manual rescoring of an event cluster."""
    async def action(session):
        event = await session.get(EventCluster, identifier)
        if event is None:
            typer.echo("Event cluster not found")
            raise typer.Exit(1)
        market_score = await market_move_score_for_cluster(session, event)
        breakdown = score_event(
            ScoreInput(
                top_source_score=event.top_source_score,
                source_count=event.source_count,
                watchlist_tier="D",
                is_duplicate=False,
                is_stale=event.status == "stale",
                status=event.status,
                market_move_score=market_score,
            )
        )
        event.market_impact_score = breakdown.market_move_score
        event.confirmation_score = breakdown.confidence_score
        event.novelty_score = breakdown.novelty_score
        event.urgency_score = breakdown.urgency_score
        event.relevance_score = breakdown.relevance_score
        event.final_score = breakdown.final_score
        session.add(
            EventScoreHistory(
                event_cluster_id=event.id,
                score_breakdown=breakdown.__dict__,
                final_score=breakdown.final_score,
            )
        )
        _echo_json(
            {
                "id": event.id,
                "final_score": event.final_score,
                "score_breakdown": breakdown.__dict__,
            }
        )

    _run(_with_session(action))


@event_app.command("mark")
def event_mark(identifier: str, status: Annotated[str, typer.Option("--status")]) -> None:
    """Change status of an event cluster."""
    allowed = {"reported", "confirmed", "official", "stale", "false_signal", "merged"}
    if status not in allowed:
        typer.echo(f"status must be one of: {', '.join(sorted(allowed))}")
        raise typer.Exit(1)

    async def action(session):
        event = await session.get(EventCluster, identifier)
        if event is None:
            typer.echo("Event cluster not found")
            raise typer.Exit(1)
        event.status = status
        _echo_json({"id": event.id, "status": event.status})

    _run(_with_session(action))
