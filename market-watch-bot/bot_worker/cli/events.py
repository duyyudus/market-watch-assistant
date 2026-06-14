from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Annotated

import typer
from sqlalchemy import select

from bot_worker.cli.apps import event_app
from bot_worker.cli.common import _echo_json, _run, _settings, _with_session
from bot_worker.db.models import (
    AgentInvestigation,
    AlertDecisionRecord,
    EventCluster,
    EventScoreHistory,
)
from bot_worker.embeddings import EmbeddingConfig
from bot_worker.services import (
    compact_archived_events,
    digest_preview,
    event_report_time_range,
    format_report_time_range,
    recluster_recent_event_clusters,
)
from bot_worker.services.bot_commands import apply_event_score, score_event_cluster
from bot_worker.services.events import merge_event_clusters, split_event_cluster
from common.llm import LLMConfig


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
    source: str,
    target: str,
    confirm: Annotated[bool, typer.Option("--confirm")] = False,
) -> None:
    """Merge one event cluster into another and move its news items."""
    if not confirm:
        typer.echo("Use --confirm to merge event clusters.")
        raise typer.Exit(1)

    async def action(session):
        _echo_json(await merge_event_clusters(session, source_id=source, target_id=target))

    _run(_with_session(action))


@event_app.command("split")
def event_split(
    event_id: str,
    news_ids: str,
    confirm: Annotated[bool, typer.Option("--confirm")] = False,
) -> None:
    """Split selected news items into a new event cluster."""
    if not confirm:
        typer.echo("Use --confirm to split event clusters.")
        raise typer.Exit(1)
    parsed_news_ids = [item.strip() for item in news_ids.split(",") if item.strip()]

    async def action(session):
        _echo_json(
            await split_event_cluster(
                session,
                source_id=event_id,
                news_item_ids=parsed_news_ids,
            )
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
    limit: Annotated[int | None, typer.Option("--limit")] = None,
    use_llm: Annotated[bool, typer.Option("--llm")] = False,
    use_embed: Annotated[bool, typer.Option("--embed")] = False,
) -> None:
    """Recluster recent event items; dry-run by default.

    Pass --llm to let the model arbitrate ambiguous (gray-zone) groupings, and/or
    --embed to merge near-duplicate items by embedding similarity (catches paraphrases
    lexical matching misses). Without either, the regroup is deterministic-only. Both
    flags run during dry-run too, so the preview reflects what --apply would produce.

    Surviving clusters are always re-embedded on --apply (no --embed needed) whenever
    embeddings are configured, since recluster invalidates their stored vectors.

    Scope is controlled by --since; --limit is an optional cap on the number of clusters
    and is unbounded by default.
    """
    if apply and not confirm:
        typer.echo("Use --confirm with --apply to mutate event clusters.")
        raise typer.Exit(1)
    since = _since_cutoff(since_value)
    settings = _settings()
    llm_config: LLMConfig | None = None
    if use_llm:
        llm_config = LLMConfig.from_settings(settings)
        if not llm_config.enabled:
            llm_config = replace(llm_config, enabled=True)
        if not llm_config.api_key:
            typer.echo("--llm requested but no LLM API key is configured.")
            raise typer.Exit(1)
    # Build the embedding config whenever embeddings are usable, independent of --embed:
    # recluster always invalidates cluster embeddings on apply, so it always re-embeds the
    # surviving clusters to avoid leaving them invisible to live vector attach. --embed is a
    # separate opt-in that *also* uses stored vectors as a grouping signal during regroup.
    embedding_config: EmbeddingConfig | None = EmbeddingConfig.from_settings(settings)
    if embedding_config.provider != "local" and not embedding_config.api_key:
        embedding_config = None

    def _progress(phase: str, done: int, total: int) -> None:
        typer.echo(f"\r  {phase} {done}/{total}…", nl=False, err=True)
        if done == total:
            typer.echo("", err=True)

    async def action(session):
        result = await recluster_recent_event_clusters(
            session,
            since=since,
            dry_run=not apply,
            limit=limit,
            progress=_progress,
            llm_config=llm_config,
            embedding_config=embedding_config,
            use_vector_signal=use_embed,
        )
        _echo_json(result)

    _run(_with_session(action))


@event_app.command("compact-archived")
def event_compact_archived(
    older_than_value: Annotated[str, typer.Option("--older-than")] = "30d",
    apply: Annotated[bool, typer.Option("--apply")] = False,
    confirm: Annotated[bool, typer.Option("--confirm")] = False,
    limit: Annotated[int, typer.Option("--limit")] = 500,
) -> None:
    """Compact old archive-only event data; dry-run by default."""
    if apply and not confirm:
        typer.echo("Use --confirm with --apply to compact archived events.")
        raise typer.Exit(1)
    older_than = _since_cutoff(older_than_value)

    async def action(session):
        result = await compact_archived_events(
            session,
            older_than=older_than,
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
        breakdown = await score_event_cluster(session, event)
        apply_event_score(event, breakdown)
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
