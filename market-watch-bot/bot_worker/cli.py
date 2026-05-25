from __future__ import annotations

import asyncio
import json
import subprocess
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated
from zoneinfo import ZoneInfo

import typer
from sqlalchemy import select, text

from bot_worker.config import Settings, load_settings, starter_sources_yaml, write_default_files
from bot_worker.db.models import AlertDecisionRecord, EventCluster
from bot_worker.db.session import make_engine, make_session_factory
from bot_worker.digest import digest_window_for_date
from bot_worker.embeddings import EmbeddingConfig
from bot_worker.retention import RetentionPolicy, retention_cutoffs
from bot_worker.scoring import AlertThresholds, decide_alert
from bot_worker.services import (
    CORE_JOBS,
    add_source,
    add_watchlist_entry,
    digest_display_headline,
    digest_preview,
    embed_pending_event_clusters,
    embed_pending_news_items,
    fetch_market_moves,
    fetch_source,
    get_source,
    import_sources_yaml,
    list_sources,
    purge_source,
    record_job_run,
    retention_preview,
    run_missed_catalyst_review,
    run_pipeline,
    run_retention,
    seed_starter_sources,
    set_source_enabled,
    store_market_moves,
    watchlist_entries,
)
from bot_worker.watchlist import match_watchlist

app = typer.Typer(no_args_is_help=True, help="Market watch bot CLI")
source_app = typer.Typer(no_args_is_help=True)
worker_app = typer.Typer(no_args_is_help=True)
job_app = typer.Typer(no_args_is_help=True)
pipeline_app = typer.Typer(no_args_is_help=True)
news_app = typer.Typer(no_args_is_help=True)
event_app = typer.Typer(no_args_is_help=True)
watchlist_app = typer.Typer(no_args_is_help=True)
alert_app = typer.Typer(no_args_is_help=True)
alert_policy_app = typer.Typer(no_args_is_help=True)
digest_app = typer.Typer(no_args_is_help=True)
retention_app = typer.Typer(no_args_is_help=True)
health_app = typer.Typer(no_args_is_help=True)
embedding_app = typer.Typer(no_args_is_help=True)
market_app = typer.Typer(no_args_is_help=True)
catalyst_app = typer.Typer(no_args_is_help=True)

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
    source_test(identifier)


@source_app.command("enable")
def source_enable(identifier: str) -> None:
    async def action(session):
        ok = await set_source_enabled(session, identifier, True)
        typer.echo("enabled" if ok else "source not found")

    _run(_with_session(action))


@source_app.command("disable")
def source_disable(identifier: str) -> None:
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
                )
                await record_job_run(session, "pipeline", result)
                typer.echo(f"pipeline: {result}")

            await _with_session(action)
            await asyncio.sleep(_settings().bot.polling_interval_seconds)

    _run(loop())


@worker_app.command("status")
def worker_status() -> None:
    typer.echo("worker status: command-driven MVP; no supervisor state recorded")


@worker_app.command("logs")
def worker_logs(tail: Annotated[int, typer.Option("--tail")] = 200) -> None:
    typer.echo(f"worker logs are stdout/stderr in MVP (tail requested: {tail})")


@worker_app.command("health")
def worker_health() -> None:
    health_pipeline()


@job_app.command("list")
def job_list() -> None:
    for job in CORE_JOBS:
        typer.echo(job)


@job_app.command("run")
def job_run(name: str, dry_run: Annotated[bool, typer.Option("--dry-run")] = False) -> None:
    if name == "pipeline":
        pipeline_run(dry_run=dry_run)
        return
    if name == "retention_cleanup":
        retention_run()
        return
    typer.echo(f"Job {name} is registered; direct implementation is deferred in MVP")


@job_app.command("history")
def job_history() -> None:
    typer.echo(
        "job history is stored in job_runs; use database queries for detailed MVP inspection"
    )


@job_app.command("failures")
def job_failures() -> None:
    typer.echo("failed job retry queue is deferred in MVP")


@pipeline_app.command("run")
def pipeline_run(dry_run: Annotated[bool, typer.Option("--dry-run")] = False) -> None:
    if dry_run:
        typer.echo(
            "Dry run pipeline: poll -> normalize -> dedupe -> embed -> "
            "cluster -> market -> score -> alert"
        )
        return

    async def action(session):
        settings = _settings()
        result = await run_pipeline(
            session,
            freshness_hours=settings.ingestion.rss_freshness_hours,
            embedding_config=EmbeddingConfig.from_settings(settings),
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
    typer.echo(f"Pipeline inspection for {item} is available after database ingestion")


@pipeline_app.command("stats")
def pipeline_stats() -> None:
    health_pipeline()


@news_app.command("list")
def news_list() -> None:
    typer.echo("news list requires database-backed normalized_news_items")


@news_app.command("show")
def news_show(identifier: str) -> None:
    typer.echo(f"news show {identifier} requires database-backed normalized_news_items")


@news_app.command("search")
def news_search(query: str) -> None:
    typer.echo(f"news search for {query!r} uses title/snippet metadata in MVP")


@event_app.command("list")
def event_list() -> None:
    async def action(session):
        rows = await digest_preview(session)
        for event in rows:
            typer.echo(
                f"{event.id}\t{event.final_score}\t{event.status}\t{event.canonical_headline}"
            )

    _run(_with_session(action))


@event_app.command("show")
def event_show(identifier: str) -> None:
    typer.echo(f"event show {identifier} requires event_clusters data")


@event_app.command("merge")
def event_merge(left: str, right: str) -> None:
    typer.echo(f"event merge requested for {left} and {right}; manual merge is deferred in MVP")


@event_app.command("rescore")
def event_rescore(identifier: str) -> None:
    typer.echo(f"event rescore requested for {identifier}; scoring runs during pipeline in MVP")


@event_app.command("mark")
def event_mark(identifier: str, status: Annotated[str, typer.Option("--status")]) -> None:
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
    async def action(session):
        rows = await watchlist_entries(session)
        for row in rows:
            typer.echo(f"{row.symbol or '-'}\t{row.name}\t{row.tier}\t{row.entity_type}")

    _run(_with_session(action))


@watchlist_app.command("show")
def watchlist_show(identifier: str) -> None:
    typer.echo(f"watchlist show {identifier} is deferred in MVP")


@watchlist_app.command("match")
def watchlist_match(text_value: str) -> None:
    async def action(session):
        matches = match_watchlist(text_value, await watchlist_entries(session))
        if not matches:
            typer.echo("No matches")
        for match in matches:
            typer.echo(f"{match.symbol or '-'}\t{match.name}\t{match.tier}\t{match.entity_type}")

    _run(_with_session(action))


@alert_policy_app.command("show")
def alert_policy_show() -> None:
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
    typer.echo(
        f"Policy setting {key}={value} accepted for runtime config; "
        "persistent edit is manual in MVP"
    )


@alert_policy_app.command("reset")
def alert_policy_reset() -> None:
    typer.echo("Alert policy reset uses defaults from settings.yml in MVP")


@alert_app.command("test")
def alert_test(score: Annotated[int, typer.Option("--score")] = 80) -> None:
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
    typer.echo("digest history is represented by event and alert history in MVP")


@retention_app.command("show")
def retention_show() -> None:
    settings = _settings()
    _echo_json(settings.retention.model_dump())


@retention_app.command("preview")
def retention_preview_command() -> None:
    settings = _settings()
    policy = RetentionPolicy(**settings.retention.model_dump())

    async def action(session):
        _echo_json(await retention_preview(session, policy))

    _run(_with_session(action))


@retention_app.command("run")
def retention_run() -> None:
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
    async def action(session):
        count = await run_missed_catalyst_review(session, window=window)
        _echo_json({"created": count, "window": window})

    _run(_with_session(action))


@health_app.command("sources")
def health_sources() -> None:
    source_list()


@health_app.command("jobs")
def health_jobs() -> None:
    job_list()


@health_app.command("db")
def health_db() -> None:
    doctor()


@health_app.command("pipeline")
def health_pipeline() -> None:
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
