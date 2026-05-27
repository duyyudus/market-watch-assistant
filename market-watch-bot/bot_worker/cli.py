from __future__ import annotations

import asyncio
import json
import subprocess
from collections.abc import Awaitable, Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated
from zoneinfo import ZoneInfo

import typer
from sqlalchemy import select, text

from bot_worker.config import Settings, load_settings, starter_sources_yaml, write_default_files
from bot_worker.db.models import (
    AlertDecisionRecord,
    EventCluster,
    LLMAnalysisRun,
    NormalizedNewsItem,
)
from bot_worker.db.session import make_engine, make_session_factory
from bot_worker.digest import digest_window_for_date
from bot_worker.embeddings import EmbeddingConfig
from bot_worker.llm import LLMConfig, build_event_analysis_prompt
from bot_worker.retention import RetentionPolicy, retention_cutoffs
from bot_worker.scoring import AlertThresholds, decide_alert
from bot_worker.services import (
    CORE_JOBS,
    add_source,
    add_watchlist_entry,
    classify_news_item_with_llm,
    digest_display_headline,
    digest_preview,
    embed_pending_event_clusters,
    embed_pending_news_items,
    enrich_event_clusters_with_llm,
    fetch_market_moves,
    fetch_source,
    get_source,
    import_sources_yaml,
    latest_llm_analysis,
    latest_successful_llm_analysis,
    list_sources,
    purge_source,
    record_job_run,
    retention_preview,
    run_missed_catalyst_review,
    run_pipeline,
    run_retention,
    score_event_with_llm,
    seed_starter_sources,
    set_source_enabled,
    store_market_moves,
    summarize_event_with_llm,
    watchlist_entries,
)
from bot_worker.watchlist import match_watchlist

_CONTEXT_SETTINGS = {"help_option_names": ["-h", "--help"]}

app = typer.Typer(
    no_args_is_help=True,
    help="Market watch bot CLI",
    context_settings=_CONTEXT_SETTINGS,
)
source_app = typer.Typer(no_args_is_help=True, context_settings=_CONTEXT_SETTINGS)
worker_app = typer.Typer(no_args_is_help=True, context_settings=_CONTEXT_SETTINGS)
job_app = typer.Typer(no_args_is_help=True, context_settings=_CONTEXT_SETTINGS)
pipeline_app = typer.Typer(no_args_is_help=True, context_settings=_CONTEXT_SETTINGS)
news_app = typer.Typer(no_args_is_help=True, context_settings=_CONTEXT_SETTINGS)
event_app = typer.Typer(no_args_is_help=True, context_settings=_CONTEXT_SETTINGS)
watchlist_app = typer.Typer(no_args_is_help=True, context_settings=_CONTEXT_SETTINGS)
alert_app = typer.Typer(no_args_is_help=True, context_settings=_CONTEXT_SETTINGS)
alert_policy_app = typer.Typer(no_args_is_help=True, context_settings=_CONTEXT_SETTINGS)
digest_app = typer.Typer(no_args_is_help=True, context_settings=_CONTEXT_SETTINGS)
retention_app = typer.Typer(no_args_is_help=True, context_settings=_CONTEXT_SETTINGS)
health_app = typer.Typer(no_args_is_help=True, context_settings=_CONTEXT_SETTINGS)
embedding_app = typer.Typer(no_args_is_help=True, context_settings=_CONTEXT_SETTINGS)
market_app = typer.Typer(no_args_is_help=True, context_settings=_CONTEXT_SETTINGS)
catalyst_app = typer.Typer(no_args_is_help=True, context_settings=_CONTEXT_SETTINGS)
llm_app = typer.Typer(no_args_is_help=True, context_settings=_CONTEXT_SETTINGS)

app.add_typer(source_app, name="source")
app.add_typer(worker_app, name="worker")
app.add_typer(job_app, name="job")
app.add_typer(pipeline_app, name="pipeline")
app.add_typer(news_app, name="news")
app.add_typer(event_app, name="event")
app.add_typer(watchlist_app, name="watchlist")
app.add_typer(alert_app, name="alert")
alert_app.add_typer(alert_policy_app, name="policy")
app.add_typer(digest_app, name="digest")
app.add_typer(retention_app, name="retention")
app.add_typer(health_app, name="health")
app.add_typer(embedding_app, name="embedding")
app.add_typer(market_app, name="market")
app.add_typer(catalyst_app, name="catalyst")
app.add_typer(llm_app, name="llm")


@app.callback()
def main() -> None:
    """Initialize logging for CLI commands."""
    from bot_worker.logging import setup_logging
    setup_logging(_settings())


def _settings() -> Settings:
    return load_settings()



def _run(coro: Awaitable[object]) -> object:
    return asyncio.run(coro)


async def _with_session(fn: Callable) -> object:
    settings = _settings()
    factory = make_session_factory(settings)
    async with factory() as session, session.begin():
        return await fn(session)


def _echo_json(data: object) -> None:
    typer.echo(json.dumps(data, indent=2, sort_keys=True, default=str))


def _db_error(exc: Exception) -> None:
    typer.echo(f"Database unavailable: {exc}")


@app.command()
def init(
    project_dir: Annotated[Path, typer.Option(help="Directory for runtime files")] = Path("."),
) -> None:
    """Create default .env, .env.example, settings.yml, and starter source YAML."""
    write_default_files(project_dir)
    sources_file = project_dir / "starter-sources.yml"
    if not sources_file.exists():
        sources_file.write_text(starter_sources_yaml(), encoding="utf-8")
    typer.echo(f"Initialized market-watch-bot files in {project_dir}")


@app.command()
def migrate() -> None:
    """Run Alembic migrations against DATABASE_URL."""
    result = subprocess.run(["uv", "run", "alembic", "upgrade", "head"], check=False)
    if result.returncode == 0:
        async def action(session):
            added = await seed_starter_sources(session)
            typer.echo(f"Seeded {added} starter sources")

        try:
            _run(_with_session(action))
        except Exception as exc:  # noqa: BLE001
            _db_error(exc)
            raise typer.Exit(1) from exc
    raise typer.Exit(result.returncode)


@app.command()
def doctor() -> None:
    """Check configuration, database connectivity, and pgvector availability."""
    settings = _settings()
    typer.echo(f"app: {settings.app.name}")
    typer.echo(f"environment: {settings.app.environment}")
    typer.echo(f"database_url: {settings.database_url}")

    async def check() -> None:
        engine = make_engine(settings)
        try:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
                vector = await conn.scalar(
                    text("SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector')")
                )
                typer.echo("database reachable: yes")
                typer.echo(f"pgvector installed: {'yes' if vector else 'no'}")
        finally:
            await engine.dispose()

    try:
        _run(check())
    except Exception as exc:  # noqa: BLE001 - doctor reports environment diagnostics
        _db_error(exc)
    typer.echo(f"openrouter configured: {'yes' if settings.openrouter_api_key else 'no'}")
    typer.echo(f"alert channel: {settings.alerts.default_channel}")


@source_app.command("add")
def source_add(
    kind: Annotated[str, typer.Argument(help="Source type, usually rss")] = "rss",
    name: Annotated[str, typer.Option("--name")] = "",
    url: Annotated[str, typer.Option("--url")] = "",
    region: Annotated[str, typer.Option("--region")] = "global",
    category: Annotated[str, typer.Option("--category")] = "global_macro",
    language: Annotated[str, typer.Option("--language")] = "en",
    score: Annotated[int, typer.Option("--score")] = 60,
    interval: Annotated[int, typer.Option("--interval")] = 300,
) -> None:
    """Add a new data source (e.g., RSS feed) to the database."""
    async def action(session):
        source = await add_source(
            session,
            name=name,
            url=url,
            region=region,
            category=category,
            source_type=kind,
            language=language,
            score=score,
            interval=interval,
        )
        typer.echo(f"Added source {source.id}: {source.name}")

    try:
        _run(_with_session(action))
    except Exception as exc:  # noqa: BLE001
        _db_error(exc)
        raise typer.Exit(1) from exc


@source_app.command("list")
def source_list(enabled: Annotated[bool, typer.Option("--enabled")] = False) -> None:
    """List all ingestion sources, optionally filtering by enabled status."""
    async def action(session):
        rows = await list_sources(session, enabled=True if enabled else None)
        if not rows:
            typer.echo("No sources found")
        for source in rows:
            state = "enabled" if source.enabled else "disabled"
            typer.echo(f"{source.id}\t{source.name}\t{source.region}\t{source.category}\t{state}")

    try:
        _run(_with_session(action))
    except Exception as exc:  # noqa: BLE001
        _db_error(exc)


@source_app.command("show")
def source_show(identifier: str) -> None:
    """Show the details and current configuration of a specific source."""
    async def action(session):
        source = await get_source(session, identifier)
        if source is None:
            typer.echo("Source not found")
            raise typer.Exit(1)
        _echo_json(
            {
                "id": source.id,
                "name": source.name,
                "url": source.url,
                "region": source.region,
                "category": source.category,
                "enabled": source.enabled,
                "score": source.source_score,
            }
        )

    _run(_with_session(action))


@source_app.command("test")
def source_test(identifier: str) -> None:
    """Test fetching and parsing a source without saving the items to the database."""
    async def action(session):
        source = await get_source(session, identifier)
        if source is None:
            typer.echo("Source not found")
            raise typer.Exit(1)
        result = await fetch_source(session, source)
        _echo_json(result)

    _run(_with_session(action))


@source_app.command("fetch")
def source_fetch(identifier: str) -> None:
    """Fetch and test a source (alias for 'source test')."""
    source_test(identifier)


@source_app.command("enable")
def source_enable(identifier: str) -> None:
    """Enable a specific data source by its identifier."""
    async def action(session):
        ok = await set_source_enabled(session, identifier, True)
        typer.echo("enabled" if ok else "source not found")

    _run(_with_session(action))


@source_app.command("disable")
def source_disable(identifier: str) -> None:
    """Disable a specific data source by its identifier."""
    async def action(session):
        ok = await set_source_enabled(session, identifier, False)
        typer.echo("disabled" if ok else "source not found")

    _run(_with_session(action))


@source_app.command("purge")
def source_purge(
    identifier: str,
    yes: Annotated[
        bool, typer.Option("--yes", help="Confirm permanent deletion of the source and its data")
    ] = False,
) -> None:
    """Permanently delete a source and all its associated news items and events."""
    if not yes:
        typer.echo("Refusing to purge without --yes")
        raise typer.Exit(1)

    async def action(session):
        result = await purge_source(session, identifier)
        if result.get("status") == "not_found":
            typer.echo("source not found")
            raise typer.Exit(1)
        typer.echo(f"Purged source {result['source']}")
        for key, value in result.items():
            if key in {"status", "source"}:
                continue
            typer.echo(f"{key}: {value}")

    _run(_with_session(action))


@source_app.command("import")
def source_import(path: Path) -> None:
    """Import multiple data sources from a YAML configuration file."""
    sources = import_sources_yaml(path)

    async def action(session):
        count = 0
        for source in sources:
            await add_source(
                session,
                name=str(source["name"]),
                url=str(source["url"]),
                region=str(source.get("region", "global")),
                category=str(source.get("category", "global_macro")),
                source_type=str(source.get("type", "rss")),
                language=str(source.get("language", "en")),
                score=int(source.get("score", 60)),
                interval=int(source.get("interval", 300)),
            )
            count += 1
        typer.echo(f"Imported {count} sources")

    _run(_with_session(action))


@source_app.command("export")
def source_export(out: Annotated[Path, typer.Option("--out")] = Path("sources.yaml")) -> None:
    """Export all defined data sources to a YAML file."""
    async def action(session):
        rows = await list_sources(session)
        data = {
            "sources": [
                {
                    "name": source.name,
                    "url": source.url,
                    "region": source.region,
                    "category": source.category,
                    "type": source.source_type,
                    "language": source.language,
                    "score": source.source_score,
                    "interval": source.polling_interval_seconds,
                }
                for source in rows
            ]
        }
        import yaml

        out.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
        typer.echo(f"Exported {len(rows)} sources to {out}")

    _run(_with_session(action))


@worker_app.command("start")
def worker_start(only: Annotated[str | None, typer.Option("--only")] = None) -> None:
    """Start the background worker process to run pipeline jobs at configured intervals."""
    jobs = only.split(",") if only else CORE_JOBS
    typer.echo(f"Starting worker loop for jobs: {', '.join(jobs)}")
    typer.echo("Use Ctrl+C to stop")

    async def loop() -> None:
        while True:

            async def action(session):
                settings = _settings()
                result = await run_pipeline(
                    session,
                    freshness_hours=settings.ingestion.rss_freshness_hours,
                    embedding_config=EmbeddingConfig.from_settings(settings),
                    llm_config=LLMConfig.from_settings(settings),
                )
                await record_job_run(session, "pipeline", result)
                typer.echo(f"pipeline: {result}")

            await _with_session(action)
            await asyncio.sleep(_settings().bot.polling_interval_seconds)

    _run(loop())


@worker_app.command("status")
def worker_status() -> None:
    """Show worker running status (MVP placeholder)."""
    typer.echo("worker status: command-driven MVP; no supervisor state recorded")


@worker_app.command("logs")
def worker_logs(tail: Annotated[int, typer.Option("--tail")] = 200) -> None:
    """Retrieve logs from the worker process (MVP placeholder)."""
    typer.echo(f"worker logs are stdout/stderr in MVP (tail requested: {tail})")


@worker_app.command("health")
def worker_health() -> None:
    """Check health status of the worker and active database session."""
    health_pipeline()


@job_app.command("list")
def job_list() -> None:
    """List all core scheduler jobs."""
    for job in CORE_JOBS:
        typer.echo(job)


@job_app.command("run")
def job_run(name: str, dry_run: Annotated[bool, typer.Option("--dry-run")] = False) -> None:
    """Run a specific background job immediately."""
    if name == "pipeline":
        pipeline_run(dry_run=dry_run)
        return
    if name == "retention_cleanup":
        retention_run()
        return
    typer.echo(f"Job {name} is registered; direct implementation is deferred in MVP")


@job_app.command("history")
def job_history() -> None:
    """View the execution history of scheduler jobs (MVP placeholder)."""
    typer.echo(
        "job history is stored in job_runs; use database queries for detailed MVP inspection"
    )


@job_app.command("failures")
def job_failures() -> None:
    """List or inspect failed job executions (MVP placeholder)."""
    typer.echo("failed job retry queue is deferred in MVP")


@pipeline_app.command("run")
def pipeline_run(dry_run: Annotated[bool, typer.Option("--dry-run")] = False) -> None:
    """Execute the complete market watch ingestion and analysis pipeline."""
    if dry_run:
        typer.echo(
            "Dry run pipeline: poll -> normalize -> dedupe -> embed -> "
            "cluster -> llm enrich -> market -> score -> alert"
        )
        return

    async def action(session):
        settings = _settings()
        result = await run_pipeline(
            session,
            freshness_hours=settings.ingestion.rss_freshness_hours,
            embedding_config=EmbeddingConfig.from_settings(settings),
            llm_config=LLMConfig.from_settings(settings),
        )
        await record_job_run(session, "pipeline", result)
        _echo_json(result)

    try:
        _run(_with_session(action))
    except Exception as exc:  # noqa: BLE001
        _db_error(exc)
        raise typer.Exit(1) from exc


@pipeline_app.command("inspect")
def pipeline_inspect(item: Annotated[str, typer.Option("--item")]) -> None:
    """Inspect details of a specific pipeline run or item (MVP placeholder)."""
    typer.echo(f"Pipeline inspection for {item} is available after database ingestion")


@pipeline_app.command("stats")
def pipeline_stats() -> None:
    """Show statistics and retention cutoffs for the pipeline."""
    health_pipeline()


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


@watchlist_app.command("add")
def watchlist_add(
    name: Annotated[str, typer.Option("--name")],
    symbol: Annotated[str | None, typer.Option("--symbol")] = None,
    entity_type: Annotated[str, typer.Option("--type")] = "macro_theme",
    region: Annotated[str | None, typer.Option("--region")] = None,
    asset_class: Annotated[str | None, typer.Option("--asset-class")] = None,
    tier: Annotated[str, typer.Option("--tier")] = "D",
    alias: Annotated[list[str] | None, typer.Option("--alias")] = None,
) -> None:
    """Add a symbol, entity, or theme to the active watchlist."""
    async def action(session):
        entry = await add_watchlist_entry(
            session,
            name=name,
            symbol=symbol,
            tier=tier,
            entity_type=entity_type,
            region=region,
            asset_class=asset_class,
            aliases=alias or [],
        )
        typer.echo(f"Added watchlist entry {entry.id}: {entry.name}")

    _run(_with_session(action))


@watchlist_app.command("list")
def watchlist_list() -> None:
    """List all items currently in the watchlist."""
    async def action(session):
        rows = await watchlist_entries(session)
        for row in rows:
            typer.echo(f"{row.symbol or '-'}\t{row.name}\t{row.tier}\t{row.entity_type}")

    _run(_with_session(action))


@watchlist_app.command("show")
def watchlist_show(identifier: str) -> None:
    """Show details of a specific watchlist entry (MVP placeholder)."""
    typer.echo(f"watchlist show {identifier} is deferred in MVP")


@watchlist_app.command("match")
def watchlist_match(text_value: str) -> None:
    """Test matching a text value against the watchlist entries."""
    async def action(session):
        matches = match_watchlist(text_value, await watchlist_entries(session))
        if not matches:
            typer.echo("No matches")
        for match in matches:
            typer.echo(f"{match.symbol or '-'}\t{match.name}\t{match.tier}\t{match.entity_type}")

    _run(_with_session(action))


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


@retention_app.command("show")
def retention_show() -> None:
    """Display the active database retention policy configuration."""
    settings = _settings()
    _echo_json(settings.retention.model_dump())


@retention_app.command("preview")
def retention_preview_command() -> None:
    """Preview which database records would be cleaned up under the retention policy."""
    settings = _settings()
    policy = RetentionPolicy(**settings.retention.model_dump())

    async def action(session):
        _echo_json(await retention_preview(session, policy))

    _run(_with_session(action))


@retention_app.command("run")
def retention_run() -> None:
    """Execute retention cleanup to purge expired news, event, and run records."""
    settings = _settings()
    policy = RetentionPolicy(**settings.retention.model_dump())

    async def action(session):
        _echo_json(await run_retention(session, policy))

    _run(_with_session(action))


@embedding_app.command("backfill")
def embedding_backfill(
    kind: Annotated[str, typer.Option("--kind")] = "news",
    limit: Annotated[int, typer.Option("--limit", min=1, max=1000)] = 100,
) -> None:
    """Backfill vector embeddings for pending news items or event clusters."""
    settings = _settings()
    config = EmbeddingConfig.from_settings(settings)

    async def action(session):
        if kind == "news":
            count = await embed_pending_news_items(session, config=config, limit=limit)
        elif kind == "events":
            count = await embed_pending_event_clusters(session, config=config, limit=limit)
        else:
            typer.echo("kind must be news or events")
            raise typer.Exit(1)
        _echo_json({"kind": kind, "embedded": count, "provider": config.provider})

    _run(_with_session(action))


@market_app.command("fetch")
def market_fetch(
    symbols: Annotated[str, typer.Option("--symbols")],
    window: Annotated[str, typer.Option("--window")] = "1d",
) -> None:
    """Fetch recent market moves for watchlisted assets and store them in the database."""
    settings = _settings()
    parsed_symbols = [symbol.strip() for symbol in symbols.split(",") if symbol.strip()]

    async def action(session):
        moves = await fetch_market_moves(
            symbols=parsed_symbols,
            window=window,
            vn_base_url=settings.market_data.vn_base_url,
            symbol_map=settings.market_data.symbol_map,
        )
        inserted = await store_market_moves(session, moves)
        _echo_json(
            {
                "inserted": inserted,
                "symbols": parsed_symbols,
            }
        )

    _run(_with_session(action))


@catalyst_app.command("review")
def catalyst_review(window: Annotated[str, typer.Option("--window")] = "1d") -> None:
    """Run automated review of missed catalysts over a specified window."""
    async def action(session):
        count = await run_missed_catalyst_review(session, window=window)
        _echo_json({"created": count, "window": window})

    _run(_with_session(action))


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


@health_app.command("sources")
def health_sources() -> None:
    """Check data ingestion source health and configuration."""
    source_list()


@health_app.command("jobs")
def health_jobs() -> None:
    """Check the status and availability of core pipeline jobs."""
    job_list()


@health_app.command("db")
def health_db() -> None:
    """Verify database connectivity, migrations, and extension compatibility."""
    doctor()


@health_app.command("pipeline")
def health_pipeline() -> None:
    """Check pipeline status and show current retention timeframes."""
    typer.echo("pipeline jobs:")
    for job in CORE_JOBS:
        typer.echo(f"- {job}")
    settings = _settings()
    cutoffs = retention_cutoffs(
        datetime.now(UTC),
        RetentionPolicy(**settings.retention.model_dump()),
    )
    typer.echo("retention cutoffs:")
    for key, value in cutoffs.items():
        typer.echo(f"- {key}: {value.isoformat()}")
