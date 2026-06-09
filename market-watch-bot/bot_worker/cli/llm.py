from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Annotated

import typer
from sqlalchemy import select

from bot_worker.cli.apps import llm_app
from bot_worker.cli.common import _echo_json, _run, _settings, _with_session
from bot_worker.db.models import (
    EventCluster,
    LLMAnalysisRun,
    NormalizedNewsItem,
)
from bot_worker.services import (
    classify_news_item_with_llm,
    enrich_event_clusters_with_llm,
    latest_llm_analysis,
    latest_successful_llm_analysis,
    score_event_with_llm,
    summarize_event_with_llm,
)
from common.llm import LLMConfig, build_event_analysis_prompt


async def _event_or_exit(session, event_id: str) -> EventCluster:
    event = await session.get(EventCluster, event_id)
    if event is None:
        typer.echo("Event cluster not found")
        raise typer.Exit(1)
    return event
async def _news_item_or_exit(session, item_id: str) -> NormalizedNewsItem:
    item = await session.get(NormalizedNewsItem, item_id)
    if item is None:
        typer.echo("News item not found")
        raise typer.Exit(1)
    return item
def _enabled_llm_config() -> LLMConfig:
    config = LLMConfig.from_settings(_settings())
    if not config.enabled:
        config = replace(config, enabled=True)
    return config
def _echo_llm_run(*, task: str, run: LLMAnalysisRun | None, target_id: str) -> None:
    if run is None:
        _echo_json({"task": task, "target": target_id, "status": "not_enriched"})
        return
    payload = {
        "task": task,
        "target": target_id,
        "target_type": run.target_type,
        "run_id": run.id,
        "status": run.status,
        "prompt_version": run.prompt_version,
        "result": run.result,
    }
    if run.error_message:
        payload["error"] = run.error_message
    _echo_json(payload)
@llm_app.command("test")
def llm_test(
    event_id: Annotated[str, typer.Option("--event")],
    show_prompt: Annotated[bool, typer.Option("--show-prompt")] = False,
) -> None:
    """Test building the LLM analysis prompt for a specific event cluster."""
    async def action(session):
        event = await _event_or_exit(session, event_id)
        prompt = build_event_analysis_prompt(
            event,
            score_breakdown={"final_score": event.final_score},
            market_move_score=0,
        )
        if show_prompt:
            typer.echo(prompt)
            return
        _echo_json({"event": event.id, "prompt_chars": len(prompt)})

    _run(_with_session(action))
@llm_app.command("classify")
def llm_classify(item_id: Annotated[str, typer.Option("--item")]) -> None:
    """Run LLM classification and category analysis on a specific news item."""
    config = _enabled_llm_config()

    async def action(session):
        await _news_item_or_exit(session, item_id)
        run = await classify_news_item_with_llm(
            session,
            item_id=item_id,
            config=config,
            force=True,
        )
        _echo_llm_run(task="classify", run=run, target_id=item_id)

    _run(_with_session(action))
@llm_app.command("enrich")
def llm_enrich(event_id: Annotated[str, typer.Option("--event")]) -> None:
    """Trigger manual LLM enrichment (entity extraction, region mapping) for an event cluster."""
    config = _enabled_llm_config()

    async def action(session):
        await _event_or_exit(session, event_id)
        count = await enrich_event_clusters_with_llm(
            session,
            config=config,
            event_cluster_id=event_id,
            force=True,
        )
        run = await latest_successful_llm_analysis(session, event_id)
        if run is None:
            latest_run = await latest_llm_analysis(
                session,
                event_id,
                prompt_version=config.prompt_version,
            )
            if latest_run is None:
                _echo_json({"event": event_id, "enriched": count, "status": "not_enriched"})
                return
            _echo_json(
                {
                    "event": event_id,
                    "enriched": count,
                    "run_id": latest_run.id,
                    "status": latest_run.status,
                    "error": latest_run.error_message,
                }
            )
            return
        _echo_json({"event": event_id, "enriched": count, "run_id": run.id, "result": run.result})

    _run(_with_session(action))
@llm_app.command("summarize")
def llm_summarize(event_id: Annotated[str, typer.Option("--event")]) -> None:
    """Trigger manual LLM summary generation for a specific event cluster."""
    config = _enabled_llm_config()

    async def action(session):
        await _event_or_exit(session, event_id)
        run = await summarize_event_with_llm(
            session,
            event_cluster_id=event_id,
            config=config,
            force=True,
        )
        _echo_llm_run(task="summarize", run=run, target_id=event_id)

    _run(_with_session(action))
@llm_app.command("score")
def llm_score(event_id: Annotated[str, typer.Option("--event")]) -> None:
    """Trigger manual LLM scoring (impact, severity) for a specific event cluster."""
    config = _enabled_llm_config()

    async def action(session):
        await _event_or_exit(session, event_id)
        run = await score_event_with_llm(
            session,
            event_cluster_id=event_id,
            config=config,
            force=True,
        )
        _echo_llm_run(task="score", run=run, target_id=event_id)

    _run(_with_session(action))
def _since_cutoff(value: str) -> datetime:
    now = datetime.now(UTC)
    stripped = value.strip().lower()
    if stripped.endswith("d") and stripped[:-1].isdigit():
        return now - timedelta(days=int(stripped[:-1]))
    if stripped.endswith("h") and stripped[:-1].isdigit():
        return now - timedelta(hours=int(stripped[:-1]))
    return datetime.fromisoformat(value).astimezone(UTC)
@llm_app.command("usage")
def llm_usage(since: Annotated[str, typer.Option("--since")] = "7d") -> None:
    """Report total LLM token usage and run count since a specific time."""
    cutoff = _since_cutoff(since)

    async def action(session):
        rows = list(
            (
                await session.scalars(
                    select(LLMAnalysisRun).where(LLMAnalysisRun.created_at >= cutoff)
                )
            ).all()
        )
        prompt_tokens = 0
        completion_tokens = 0
        total_tokens = 0
        for row in rows:
            usage = row.usage or {}
            prompt_tokens += int(usage.get("prompt_tokens") or 0)
            completion_tokens += int(usage.get("completion_tokens") or 0)
            total_tokens += int(usage.get("total_tokens") or 0)
        _echo_json(
            {
                "since": cutoff.isoformat(),
                "runs": len(rows),
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": total_tokens,
            }
        )

    _run(_with_session(action))
