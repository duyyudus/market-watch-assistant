from __future__ import annotations

from dataclasses import asdict, replace
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
from bot_worker.scoring import ScoreInput, score_event
from bot_worker.services import (
    classify_news_item_with_llm,
    enrich_event_clusters_with_llm,
    extract_entities_with_llm,
    latest_llm_analysis,
    latest_successful_llm_analysis,
    preview_entity_extraction,
    score_event_with_llm,
    summarize_event_with_llm,
)
from bot_worker.services.market import market_move_score_for_cluster
from bot_worker.services.watchlists import tier_for_entities, watchlist_entries
from common.llm import (
    LLMAnalysis,
    LLMClassification,
    LLMConfig,
    LLMEventScore,
    LLMEventSummary,
    build_event_analysis_prompt,
    build_event_score_prompt,
    build_event_summary_prompt,
    build_news_classification_prompt,
    llm_provider,
)


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


@llm_app.command("extract-entities")
def llm_extract_entities(
    limit: Annotated[int | None, typer.Option("--limit")] = None,
    force: Annotated[bool, typer.Option("--force")] = False,
    dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
    concurrency: Annotated[int | None, typer.Option("--concurrency")] = None,
) -> None:
    """Extract entities/tickers from normalized news items via LLM classification.

    Processes all eligible items by default; pass --limit to cap the batch. By
    default items that already have entities are skipped; use --force to
    re-extract them (e.g. to backfill tickers after a classification change).
    Use --dry-run to preview how many items would be processed (no LLM calls).
    Pass --concurrency to override the configured LLM concurrency for this run.
    """
    config = _enabled_llm_config()
    if concurrency is not None:
        config = replace(config, max_concurrency=max(1, concurrency))

    async def action(session):
        if dry_run:
            preview = await preview_entity_extraction(
                session,
                config=config,
                limit=limit,
                force=force,
            )
            _echo_json({"task": "extract-entities", "dry_run": True, "force": force, **preview})
            return

        def _progress(phase: str, done: int, total: int) -> None:
            typer.echo(f"\r  {phase} {done}/{total}…", nl=False, err=True)
            if done == total:
                typer.echo("", err=True)

        extracted = await extract_entities_with_llm(
            session,
            config=config,
            limit=limit,
            force=force,
            progress=_progress,
        )
        _echo_json(
            {
                "task": "extract-entities",
                "force": force,
                "limit": limit,
                "extracted": extracted,
            }
        )

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
    """Generate a manual summary; production alerts use event enrichment."""
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
    """Generate a manual score; production alerts use event enrichment."""
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


def _format_cell(val: object) -> str:
    if val is None:
        return "N/A"
    if isinstance(val, list):
        if not val:
            return "[]"
        return "<br>".join(f"- {x}" for x in val)
    return str(val).replace("\n", "<br>")


def _generate_news_comparison_report(
    news_item: NormalizedNewsItem,
    model_a: str,
    model_b: str,
    res_a: LLMClassification | None,
    res_b: LLMClassification | None,
    usage_a: dict[str, object] | None,
    usage_b: dict[str, object] | None,
    err_a: str | None,
    err_b: str | None,
) -> str:
    def get_field(res: LLMClassification | None, err: str | None, field: str) -> str:
        if err is not None:
            return f"**Error**: {err}"
        if res is None:
            return "N/A"
        return _format_cell(getattr(res, field, None))

    def format_usage(usage: dict[str, object] | None, err: str | None) -> str:
        if err is not None:
            return f"**Error**: {err}"
        if not usage:
            return "N/A"
        prompt = usage.get("prompt_tokens", 0)
        completion = usage.get("completion_tokens", 0)
        total = usage.get("total_tokens", 0)
        return f"Prompt: {prompt}<br>Completion: {completion}<br>Total: {total}"

    lines = [
        "# LLM Model Comparison Report: News Item Classification",
        "",
        f"**Target News Item ID**: `{news_item.id}`",
        "",
        f"**Title**: {news_item.title}",
        "",
        f"**Snippet**: {news_item.snippet or ''}",
        "",
        f"**Source**: {news_item.source_name} ({news_item.source_type})",
        "",
        f"**Published At**: "
        f"{news_item.published_at.isoformat() if news_item.published_at else 'N/A'}",
        "",
        f"**Region/Asset Classes**: "
        f"{news_item.region} / {', '.join(news_item.asset_classes or [])}",
        "",
        "## Side-by-Side Comparison",
        "",
        f"| Field | Model A (`{model_a}`) | Model B (`{model_b}`) |",
        "| :--- | :--- | :--- |",
        f"| **Token Usage** | {format_usage(usage_a, err_a)} | "
        f"{format_usage(usage_b, err_b)} |",
        f"| **Item Type** | {get_field(res_a, err_a, 'item_type')} | "
        f"{get_field(res_b, err_b, 'item_type')} |",
        f"| **Actionability** | {get_field(res_a, err_a, 'actionability')} | "
        f"{get_field(res_b, err_b, 'actionability')} |",
        f"| **Event Type** | {get_field(res_a, err_a, 'event_type')} | "
        f"{get_field(res_b, err_b, 'event_type')} |",
        f"| **Region** | {get_field(res_a, err_a, 'region')} | "
        f"{get_field(res_b, err_b, 'region')} |",
        f"| **Asset Classes** | {get_field(res_a, err_a, 'asset_classes')} | "
        f"{get_field(res_b, err_b, 'asset_classes')} |",
        f"| **Entities** | {get_field(res_a, err_a, 'entities')} | "
        f"{get_field(res_b, err_b, 'entities')} |",
        f"| **Tickers** | {get_field(res_a, err_a, 'tickers')} | "
        f"{get_field(res_b, err_b, 'tickers')} |",
        f"| **Confidence** | {get_field(res_a, err_a, 'confidence')} | "
        f"{get_field(res_b, err_b, 'confidence')} |",
        f"| **Rationale** | {get_field(res_a, err_a, 'rationale')} | "
        f"{get_field(res_b, err_b, 'rationale')} |",
        "",
    ]
    return "\n".join(lines)


def _generate_event_comparison_report(
    event_cluster: EventCluster,
    model_a: str,
    model_b: str,
    enrich_a: LLMAnalysis | None,
    enrich_b: LLMAnalysis | None,
    enrich_usage_a: dict[str, object] | None,
    enrich_usage_b: dict[str, object] | None,
    enrich_err_a: str | None,
    enrich_err_b: str | None,
    summary_a: LLMEventSummary | None,
    summary_b: LLMEventSummary | None,
    summary_usage_a: dict[str, object] | None,
    summary_usage_b: dict[str, object] | None,
    summary_err_a: str | None,
    summary_err_b: str | None,
    score_a: LLMEventScore | None,
    score_b: LLMEventScore | None,
    score_usage_a: dict[str, object] | None,
    score_usage_b: dict[str, object] | None,
    score_err_a: str | None,
    score_err_b: str | None,
) -> str:
    def get_field(res: object | None, err: str | None, field: str) -> str:
        if err is not None:
            return f"**Error**: {err}"
        if res is None:
            return "N/A"
        return _format_cell(getattr(res, field, None))

    def format_usage(usage: dict[str, object] | None, err: str | None) -> str:
        if err is not None:
            return f"**Error**: {err}"
        if not usage:
            return "N/A"
        prompt = usage.get("prompt_tokens", 0)
        completion = usage.get("completion_tokens", 0)
        total = usage.get("total_tokens", 0)
        return f"Prompt: {prompt}<br>Completion: {completion}<br>Total: {total}"

    def sum_usage(usages: list[dict[str, object] | None]) -> str:
        prompt = 0
        completion = 0
        total = 0
        for usage in usages:
            if usage:
                prompt += int(usage.get("prompt_tokens") or 0)
                completion += int(usage.get("completion_tokens") or 0)
                total += int(usage.get("total_tokens") or 0)
        return f"Prompt: {prompt}<br>Completion: {completion}<br>Total: {total}"

    lines = [
        "# LLM Model Comparison Report: Event Cluster operations",
        "",
        f"**Target Event Cluster ID**: `{event_cluster.id}`",
        "",
        f"**Headline**: {event_cluster.canonical_headline}",
        "",
        f"**Deterministic Score**: {event_cluster.final_score}",
        "",
        f"**Regions/Asset Classes**: "
        f"{', '.join(event_cluster.regions or [])} / "
        f"{', '.join(event_cluster.asset_classes or [])}",
        "",
        "## Summary of Combined Token Usage",
        "",
        "| Model | Total Combined Token Usage |",
        "| :--- | :--- |",
        f"| **Model A (`{model_a}`)** | "
        f"{sum_usage([enrich_usage_a, summary_usage_a, score_usage_a])} |",
        f"| **Model B (`{model_b}`)** | "
        f"{sum_usage([enrich_usage_b, summary_usage_b, score_usage_b])} |",
        "",
        "## 1. Enrich (Event Analysis) Comparison",
        "",
        f"| Field | Model A (`{model_a}`) | Model B (`{model_b}`) |",
        "| :--- | :--- | :--- |",
        f"| **Token Usage** | {format_usage(enrich_usage_a, enrich_err_a)} | "
        f"{format_usage(enrich_usage_b, enrich_err_b)} |",
        f"| **Summary** | {get_field(enrich_a, enrich_err_a, 'summary')} | "
        f"{get_field(enrich_b, enrich_err_b, 'summary')} |",
        f"| **Event Type** | {get_field(enrich_a, enrich_err_a, 'event_type')} | "
        f"{get_field(enrich_b, enrich_err_b, 'event_type')} |",
        f"| **Status Assessment** | {get_field(enrich_a, enrich_err_a, 'status_assessment')} | "
        f"{get_field(enrich_b, enrich_err_b, 'status_assessment')} |",
        f"| **Confidence** | {get_field(enrich_a, enrich_err_a, 'confidence')} | "
        f"{get_field(enrich_b, enrich_err_b, 'confidence')} |",
        f"| **Impact Rationale** | {get_field(enrich_a, enrich_err_a, 'impact_rationale')} | "
        f"{get_field(enrich_b, enrich_err_b, 'impact_rationale')} |",
        f"| **Why It Matters** | {get_field(enrich_a, enrich_err_a, 'why_it_matters')} | "
        f"{get_field(enrich_b, enrich_err_b, 'why_it_matters')} |",
        f"| **Risk Flags** | {get_field(enrich_a, enrich_err_a, 'risk_flags')} | "
        f"{get_field(enrich_b, enrich_err_b, 'risk_flags')} |",
        f"| **Score Modifier** | {get_field(enrich_a, enrich_err_a, 'score_modifier')} | "
        f"{get_field(enrich_b, enrich_err_b, 'score_modifier')} |",
        f"| **Modifier Reason** | {get_field(enrich_a, enrich_err_a, 'modifier_reason')} | "
        f"{get_field(enrich_b, enrich_err_b, 'modifier_reason')} |",
        "",
        "## 2. Summary Generation Comparison",
        "",
        f"| Field | Model A (`{model_a}`) | Model B (`{model_b}`) |",
        "| :--- | :--- | :--- |",
        f"| **Token Usage** | {format_usage(summary_usage_a, summary_err_a)} | "
        f"{format_usage(summary_usage_b, summary_err_b)} |",
        f"| **Summary** | {get_field(summary_a, summary_err_a, 'summary')} | "
        f"{get_field(summary_b, summary_err_b, 'summary')} |",
        f"| **Status** | {get_field(summary_a, summary_err_a, 'status')} | "
        f"{get_field(summary_b, summary_err_b, 'status')} |",
        f"| **Affected Assets** | {get_field(summary_a, summary_err_a, 'affected_assets')} | "
        f"{get_field(summary_b, summary_err_b, 'affected_assets')} |",
        f"| **Digest Bullets** | {get_field(summary_a, summary_err_a, 'digest_bullets')} | "
        f"{get_field(summary_b, summary_err_b, 'digest_bullets')} |",
        f"| **Why It Matters** | {get_field(summary_a, summary_err_a, 'why_it_matters')} | "
        f"{get_field(summary_b, summary_err_b, 'why_it_matters')} |",
        f"| **Alert Message** | {get_field(summary_a, summary_err_a, 'alert_message')} | "
        f"{get_field(summary_b, summary_err_b, 'alert_message')} |",
        f"| **Caveats** | {get_field(summary_a, summary_err_a, 'caveats')} | "
        f"{get_field(summary_b, summary_err_b, 'caveats')} |",
        "",
        "## 3. Score Assessment Comparison",
        "",
        f"| Field | Model A (`{model_a}`) | Model B (`{model_b}`) |",
        "| :--- | :--- | :--- |",
        f"| **Token Usage** | {format_usage(score_usage_a, score_err_a)} | "
        f"{format_usage(score_usage_b, score_err_b)} |",
        f"| **Impact Score** | {get_field(score_a, score_err_a, 'impact_score')} | "
        f"{get_field(score_b, score_err_b, 'impact_score')} |",
        f"| **Relevance Score** | {get_field(score_a, score_err_a, 'relevance_score')} | "
        f"{get_field(score_b, score_err_b, 'relevance_score')} |",
        f"| **Confidence Score** | {get_field(score_a, score_err_a, 'confidence_score')} | "
        f"{get_field(score_b, score_err_b, 'confidence_score')} |",
        f"| **Risk Flags** | {get_field(score_a, score_err_a, 'risk_flags')} | "
        f"{get_field(score_b, score_err_b, 'risk_flags')} |",
        f"| **Score Modifier** | {get_field(score_a, score_err_a, 'score_modifier')} | "
        f"{get_field(score_b, score_err_b, 'score_modifier')} |",
        f"| **Modifier Reason** | {get_field(score_a, score_err_a, 'modifier_reason')} | "
        f"{get_field(score_b, score_err_b, 'modifier_reason')} |",
        "",
    ]
    return "\n".join(lines)


@llm_app.command("compare-model")
def llm_compare_model(
    model_a: str,
    model_b: str,
    target_ids: Annotated[
        list[str],
        typer.Argument(help="List of news or event IDs to compare"),
    ] = None,
    rerun_all: Annotated[
        bool,
        typer.Option(
            "--rerun-all",
            help="Rerun comparison against all existing reports in .llm_comparison/",
        ),
    ] = False,
) -> None:
    """Compare performance of two LLM models side-by-side on multiple news items or events."""
    config = _enabled_llm_config()
    config_a = replace(config, model=model_a)
    config_b = replace(config, model=model_b)

    async def action(session):
        import os

        ids = list(target_ids or [])
        if rerun_all and os.path.exists(".llm_comparison"):
            for filename in os.listdir(".llm_comparison"):
                if filename.startswith("llm_compare_") and filename.endswith(".md"):
                    t_id = filename[len("llm_compare_") : -len(".md")]
                    if t_id and t_id not in ids:
                        ids.append(t_id)

        if not ids:
            typer.echo(
                "Error: Please provide at least one news-or-event-id "
                "or use --rerun-all."
            )
            raise typer.Exit(1)

        provider_a = llm_provider(config_a)
        provider_b = llm_provider(config_b)

        os.makedirs(".llm_comparison", exist_ok=True)
        processed_count = 0

        for target_id in ids:
            news_item = await session.get(NormalizedNewsItem, target_id)
            event_cluster = None
            if news_item is None:
                event_cluster = await session.get(EventCluster, target_id)

            if news_item is None and event_cluster is None:
                typer.echo(
                    f"Error: Target ID '{target_id}' not found in "
                    "normalized_news_items or event_clusters. Skipping."
                )
                continue

            if news_item is not None:
                prompt = build_news_classification_prompt(news_item)

                res_a, usage_a, err_a = None, None, None
                try:
                    res_a, usage_a = await provider_a.classify_news_item(prompt)
                except Exception as e:
                    err_a = str(e)

                res_b, usage_b, err_b = None, None, None
                try:
                    res_b, usage_b = await provider_b.classify_news_item(prompt)
                except Exception as e:
                    err_b = str(e)

                report = _generate_news_comparison_report(
                    news_item=news_item,
                    model_a=model_a,
                    model_b=model_b,
                    res_a=res_a,
                    res_b=res_b,
                    usage_a=usage_a,
                    usage_b=usage_b,
                    err_a=err_a,
                    err_b=err_b,
                )
            else:
                move_score = await market_move_score_for_cluster(session, event_cluster)
                watch_entries = await watchlist_entries(session)
                base_score = score_event(
                    ScoreInput(
                        top_source_score=event_cluster.top_source_score,
                        source_count=event_cluster.source_count,
                        watchlist_tier=tier_for_entities(
                            entities=event_cluster.affected_entities or [],
                            tickers=event_cluster.affected_tickers or [],
                            entries=watch_entries,
                        ),
                        is_duplicate=False,
                        is_stale=event_cluster.status == "stale",
                        unique_high_quality_source_count=int(
                            event_cluster.high_quality_source_count or 0
                        ),
                        status=event_cluster.status,
                        market_move_score=move_score,
                    )
                )
                score_breakdown = asdict(base_score)

                enrich_prompt = build_event_analysis_prompt(
                    event_cluster,
                    score_breakdown=score_breakdown,
                    market_move_score=move_score,
                )
                summary_prompt = build_event_summary_prompt(event_cluster)
                score_prompt = build_event_score_prompt(
                    event_cluster,
                    score_breakdown=score_breakdown,
                    market_move_score=move_score,
                )

                enrich_a, enrich_usage_a, enrich_err_a = None, None, None
                summary_a, summary_usage_a, summary_err_a = None, None, None
                score_a, score_usage_a, score_err_a = None, None, None

                try:
                    enrich_a, enrich_usage_a = await provider_a.analyze_event(enrich_prompt)
                except Exception as e:
                    enrich_err_a = str(e)
                try:
                    summary_a, summary_usage_a = await provider_a.summarize_event(summary_prompt)
                except Exception as e:
                    summary_err_a = str(e)
                try:
                    score_a, score_usage_a = await provider_a.score_event(score_prompt)
                except Exception as e:
                    score_err_a = str(e)

                enrich_b, enrich_usage_b, enrich_err_b = None, None, None
                summary_b, summary_usage_b, summary_err_b = None, None, None
                score_b, score_usage_b, score_err_b = None, None, None

                try:
                    enrich_b, enrich_usage_b = await provider_b.analyze_event(enrich_prompt)
                except Exception as e:
                    enrich_err_b = str(e)
                try:
                    summary_b, summary_usage_b = await provider_b.summarize_event(summary_prompt)
                except Exception as e:
                    summary_err_b = str(e)
                try:
                    score_b, score_usage_b = await provider_b.score_event(score_prompt)
                except Exception as e:
                    score_err_b = str(e)

                report = _generate_event_comparison_report(
                    event_cluster=event_cluster,
                    model_a=model_a,
                    model_b=model_b,
                    enrich_a=enrich_a,
                    enrich_b=enrich_b,
                    enrich_usage_a=enrich_usage_a,
                    enrich_usage_b=enrich_usage_b,
                    enrich_err_a=enrich_err_a,
                    enrich_err_b=enrich_err_b,
                    summary_a=summary_a,
                    summary_b=summary_b,
                    summary_usage_a=summary_usage_a,
                    summary_usage_b=summary_usage_b,
                    summary_err_a=summary_err_a,
                    summary_err_b=summary_err_b,
                    score_a=score_a,
                    score_b=score_b,
                    score_usage_a=score_usage_a,
                    score_usage_b=score_usage_b,
                    score_err_a=score_err_a,
                    score_err_b=score_err_b,
                )

            filepath = os.path.join(".llm_comparison", f"llm_compare_{target_id}.md")
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(report)

            typer.echo(f"Comparison report saved to {filepath}")
            processed_count += 1

        if processed_count == 0:
            typer.echo("Error: No valid news-or-event-ids were found.")
            raise typer.Exit(1)

    _run(_with_session(action))
