from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter

import httpx
import yaml
from sqlalchemy import Select, delete, func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from bot_worker.config import STARTER_SOURCES, StarterSource
from bot_worker.db.models import (
    AlertDecisionRecord,
    EventCluster,
    EventClusterItem,
    JobRun,
    NewsSource,
    NormalizedNewsItem,
    RawNewsItem,
    RetentionJob,
    SourceFetchLog,
    WatchlistEntity,
    utcnow,
)
from bot_worker.events import EventCandidate, cluster_candidates
from bot_worker.normalize import (
    canonicalize_url,
    content_hash,
    normalize_datetime,
    normalize_text,
    title_hash,
)
from bot_worker.retention import RetentionPolicy, retention_cutoffs
from bot_worker.rss import ParsedFeedItem, parse_rss_items
from bot_worker.scoring import AlertThresholds, ScoreInput, decide_alert, score_event
from bot_worker.watchlist import WatchlistEntry, match_watchlist

CORE_JOBS = [
    "poll_sources",
    "normalize_raw_items",
    "dedupe_news_items",
    "extract_entities",
    "cluster_events",
    "score_events",
    "dispatch_alerts",
    "build_digest",
    "retention_cleanup",
    "source_health_check",
]


def _source_from_starter(source: StarterSource) -> NewsSource:
    return NewsSource(
        name=source.name,
        source_type=source.source_type,
        category=source.category,
        region=source.region,
        asset_classes=[source.category],
        url=source.url,
        language=source.language,
        source_score=source.source_score,
        polling_interval_seconds=source.polling_interval_seconds,
        parser_type="rss",
    )


def _json_safe(value: object) -> object:
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_json_safe(item) for item in value]
    return str(value)


def _published_to_string(value: object | None) -> str | None:
    published = normalize_datetime(value)
    return published.isoformat() if published else None


async def seed_starter_sources(session: AsyncSession) -> int:
    added = 0
    for source in STARTER_SOURCES:
        stmt = (
            insert(NewsSource)
            .values(
                name=source.name,
                source_type=source.source_type,
                category=source.category,
                region=source.region,
                asset_classes=[source.category],
                url=source.url,
                language=source.language,
                source_score=source.source_score,
                polling_interval_seconds=source.polling_interval_seconds,
                parser_type="rss",
            )
            .on_conflict_do_nothing(index_elements=["url"])
        )
        result = await session.execute(stmt)
        added += result.rowcount or 0
    return added


async def add_source(
    session: AsyncSession,
    *,
    name: str,
    url: str,
    region: str,
    category: str,
    source_type: str = "rss",
    language: str = "en",
    score: int = 60,
    interval: int = 300,
) -> NewsSource:
    source = NewsSource(
        name=name,
        url=url,
        region=region,
        category=category,
        source_type=source_type,
        language=language,
        source_score=score,
        polling_interval_seconds=interval,
        asset_classes=[category],
    )
    session.add(source)
    await session.flush()
    return source


async def list_sources(session: AsyncSession, *, enabled: bool | None = None) -> list[NewsSource]:
    stmt: Select[tuple[NewsSource]] = select(NewsSource).order_by(NewsSource.name)
    if enabled is not None:
        stmt = stmt.where(NewsSource.enabled.is_(enabled))
    return list((await session.scalars(stmt)).all())


async def get_source(session: AsyncSession, identifier: str) -> NewsSource | None:
    stmt = select(NewsSource).where(or_(NewsSource.id == identifier, NewsSource.name == identifier))
    return await session.scalar(stmt)


async def set_source_enabled(session: AsyncSession, identifier: str, enabled: bool) -> bool:
    source = await get_source(session, identifier)
    if source is None:
        return False
    source.enabled = enabled
    return True


async def fetch_source_content(source: NewsSource) -> tuple[int, str]:
    async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
        response = await client.get(source.url)
        response.raise_for_status()
        return response.status_code, response.text


def raw_item_from_parsed(source: NewsSource, item: ParsedFeedItem) -> RawNewsItem:
    raw_text = " ".join([item.title, item.description, item.url])
    return RawNewsItem(
        source_id=source.id,
        raw_title=item.title,
        raw_description=item.description,
        raw_url=item.url,
        raw_published_at=_published_to_string(item.published),
        raw_payload=_json_safe(item.raw_payload),
        content_hash=content_hash(raw_text),
    )


async def fetch_source(session: AsyncSession, source: NewsSource) -> dict[str, int | str]:
    started = perf_counter()
    try:
        http_status, body = await fetch_source_content(source)
        items = parse_rss_items(body)
        inserted = 0
        for item in items:
            stmt = (
                insert(RawNewsItem)
                .values(
                    source_id=source.id,
                    raw_title=item.title,
                    raw_description=item.description,
                    raw_url=item.url,
                    raw_published_at=_published_to_string(item.published),
                    raw_payload=_json_safe(item.raw_payload),
                    content_hash=content_hash(" ".join([item.title, item.description, item.url])),
                )
                .on_conflict_do_nothing(index_elements=["source_id", "content_hash"])
            )
            result = await session.execute(stmt)
            inserted += result.rowcount or 0
        session.add(
            SourceFetchLog(
                source_id=source.id,
                status="success",
                http_status=http_status,
                item_count=len(items),
                duration_ms=round((perf_counter() - started) * 1000),
                content_hash=content_hash(body),
            )
        )
        return {"status": "success", "items": len(items), "inserted": inserted}
    except Exception as exc:  # noqa: BLE001 - command should persist source diagnostics
        session.add(
            SourceFetchLog(
                source_id=source.id,
                status="failed",
                error_message=str(exc),
                duration_ms=round((perf_counter() - started) * 1000),
            )
        )
        return {"status": "failed", "error": str(exc)}


async def normalize_pending_raw_items(session: AsyncSession, *, limit: int = 500) -> int:
    stmt = (
        select(RawNewsItem, NewsSource)
        .join(NewsSource, NewsSource.id == RawNewsItem.source_id)
        .outerjoin(NormalizedNewsItem, NormalizedNewsItem.raw_item_id == RawNewsItem.id)
        .where(NormalizedNewsItem.id.is_(None))
        .limit(limit)
    )
    rows = (await session.execute(stmt)).all()
    inserted = 0
    for raw, source in rows:
        title = normalize_text(raw.raw_title)
        if not title or not raw.raw_url:
            continue
        snippet = normalize_text(raw.raw_description)
        canonical_url = canonicalize_url(raw.raw_url)
        item = NormalizedNewsItem(
            source_id=source.id,
            raw_item_id=raw.id,
            title=title,
            snippet=snippet or None,
            url=raw.raw_url,
            canonical_url=canonical_url,
            source_name=source.name,
            source_type=source.source_type,
            source_score=source.source_score,
            published_at=normalize_datetime(raw.raw_published_at),
            fetched_at=raw.fetched_at,
            language=source.language,
            region=source.region,
            asset_classes=source.asset_classes,
            title_hash=title_hash(title),
            canonical_url_hash=content_hash(canonical_url),
            normalized_text_hash=content_hash(f"{title} {snippet}"),
            processing_status="normalized",
        )
        session.add(item)
        inserted += 1
    return inserted


async def mark_exact_duplicates(session: AsyncSession) -> int:
    stmt = select(NormalizedNewsItem).where(NormalizedNewsItem.processing_status == "normalized")
    items = list((await session.scalars(stmt)).all())
    seen: set[tuple[str | None, str]] = set()
    duplicates = 0
    for item in items:
        key = (item.canonical_url_hash, item.title_hash)
        if key in seen:
            item.processing_status = "deduped"
            duplicates += 1
        else:
            seen.add(key)
    return duplicates


async def watchlist_entries(session: AsyncSession) -> list[WatchlistEntry]:
    rows = list(
        (
            await session.scalars(select(WatchlistEntity).where(WatchlistEntity.enabled.is_(True)))
        ).all()
    )
    return [
        WatchlistEntry(
            symbol=row.symbol,
            name=row.name,
            tier=row.tier,
            entity_type=row.entity_type,
            region=row.region,
            asset_class=row.asset_class,
            aliases=row.aliases,
            enabled=row.enabled,
        )
        for row in rows
    ]


async def add_watchlist_entry(
    session: AsyncSession,
    *,
    name: str,
    symbol: str | None,
    tier: str,
    entity_type: str,
    region: str | None,
    asset_class: str | None,
    aliases: list[str],
) -> WatchlistEntity:
    entry = WatchlistEntity(
        name=name,
        symbol=symbol,
        tier=tier,
        entity_type=entity_type,
        region=region,
        asset_class=asset_class,
        aliases=aliases,
    )
    session.add(entry)
    await session.flush()
    return entry


async def build_event_clusters(session: AsyncSession, *, limit: int = 500) -> int:
    existing_news = select(EventClusterItem.news_item_id)
    stmt = (
        select(NormalizedNewsItem)
        .where(NormalizedNewsItem.processing_status.in_(["normalized", "deduped"]))
        .where(NormalizedNewsItem.id.not_in(existing_news))
        .limit(limit)
    )
    items = list((await session.scalars(stmt)).all())
    if not items:
        return 0
    watch_entries = await watchlist_entries(session)
    candidates: list[EventCandidate] = []
    for item in items:
        matches = match_watchlist(f"{item.title} {item.snippet or ''}", watch_entries)
        entities = [match.name for match in matches] or item.title.split()[:3]
        candidates.append(
            EventCandidate(
                news_id=item.id,
                title=item.title,
                source_score=item.source_score,
                entities=entities,
                region=item.region,
                asset_classes=item.asset_classes,
                published_at=item.published_at,
            )
        )
    drafts = cluster_candidates(candidates)
    for draft in drafts:
        first_seen = utcnow()
        cluster = EventCluster(
            canonical_headline=draft.canonical_headline,
            first_seen_at=first_seen,
            last_updated_at=first_seen,
            regions=sorted(draft.regions),
            asset_classes=sorted(draft.asset_classes),
            affected_entities=sorted(draft.entities),
            source_count=draft.source_count,
            top_source_score=draft.top_source_score,
        )
        score = score_event(
            ScoreInput(
                top_source_score=draft.top_source_score,
                source_count=draft.source_count,
                watchlist_tier="A" if draft.entities else None,
                is_duplicate=False,
                is_stale=False,
            )
        )
        cluster.confirmation_score = score.confidence_score
        cluster.novelty_score = score.novelty_score
        cluster.urgency_score = score.urgency_score
        cluster.market_impact_score = score.impact_score
        cluster.relevance_score = score.relevance_score
        cluster.final_score = score.final_score
        cluster.alert_level = decide_alert(score.final_score, AlertThresholds()).decision
        session.add(cluster)
        await session.flush()
        for news_id in draft.news_ids:
            session.add(EventClusterItem(event_cluster_id=cluster.id, news_item_id=news_id))
    return len(drafts)


async def record_alert_decisions(session: AsyncSession) -> int:
    stmt = (
        select(EventCluster)
        .outerjoin(AlertDecisionRecord, AlertDecisionRecord.event_cluster_id == EventCluster.id)
        .where(AlertDecisionRecord.id.is_(None))
    )
    clusters = list((await session.scalars(stmt)).all())
    count = 0
    for cluster in clusters:
        score = score_event(
            ScoreInput(
                top_source_score=cluster.top_source_score,
                source_count=cluster.source_count,
                watchlist_tier="A" if cluster.affected_entities else None,
                is_duplicate=False,
                is_stale=cluster.status == "stale",
                status=cluster.status,
            )
        )
        decision = decide_alert(score.final_score, AlertThresholds())
        session.add(
            AlertDecisionRecord(
                event_cluster_id=cluster.id,
                decision=decision.decision,
                reason=decision.reason,
                score_breakdown=asdict(score),
                channel="log",
            )
        )
        count += 1
    return count


async def run_pipeline(session: AsyncSession, *, dry_run: bool = False) -> dict[str, int | str]:
    if dry_run:
        return {"status": "dry_run", "jobs": len(CORE_JOBS)}
    sources = list(
        (await session.scalars(select(NewsSource).where(NewsSource.enabled.is_(True)))).all()
    )
    fetched = 0
    for source in sources:
        result = await fetch_source(session, source)
        if result.get("status") == "success":
            fetched += int(result.get("inserted", 0))
    normalized = await normalize_pending_raw_items(session)
    duplicates = await mark_exact_duplicates(session)
    clusters = await build_event_clusters(session)
    alerts = await record_alert_decisions(session)
    return {
        "fetched": fetched,
        "normalized": normalized,
        "duplicates": duplicates,
        "clusters": clusters,
        "alerts": alerts,
    }


async def record_job_run(session: AsyncSession, job_name: str, result: dict[str, object]) -> JobRun:
    run = JobRun(
        job_name=job_name,
        status="success",
        completed_at=datetime.now(UTC),
        result=result,
    )
    session.add(run)
    await session.flush()
    return run


async def digest_preview(session: AsyncSession, *, limit: int = 20) -> list[EventCluster]:
    stmt = (
        select(EventCluster)
        .order_by(EventCluster.final_score.desc(), EventCluster.created_at.desc())
        .limit(limit)
    )
    return list((await session.scalars(stmt)).all())


async def retention_preview(session: AsyncSession, policy: RetentionPolicy) -> dict[str, int]:
    cutoffs = retention_cutoffs(datetime.now(UTC), policy)
    counts: dict[str, int] = {}
    counts["source_fetch_logs"] = (
        await session.scalar(
            select(func.count())
            .select_from(SourceFetchLog)
            .where(SourceFetchLog.fetched_at < cutoffs["source_fetch_logs"])
        )
        or 0
    )
    counts["raw_news_items"] = (
        await session.scalar(
            select(func.count())
            .select_from(RawNewsItem)
            .where(RawNewsItem.fetched_at < cutoffs["raw_news_items"])
        )
        or 0
    )
    counts["normalized_news_items"] = (
        await session.scalar(
            select(func.count())
            .select_from(NormalizedNewsItem)
            .where(NormalizedNewsItem.created_at < cutoffs["normalized_news_items"])
        )
        or 0
    )
    counts["event_clusters"] = (
        await session.scalar(
            select(func.count())
            .select_from(EventCluster)
            .where(EventCluster.created_at < cutoffs["event_clusters"])
        )
        or 0
    )
    counts["alert_decisions"] = (
        await session.scalar(
            select(func.count())
            .select_from(AlertDecisionRecord)
            .where(AlertDecisionRecord.created_at < cutoffs["alert_decisions"])
        )
        or 0
    )
    return counts


async def run_retention(session: AsyncSession, policy: RetentionPolicy) -> dict[str, int]:
    cutoffs = retention_cutoffs(datetime.now(UTC), policy)
    deleted: dict[str, int] = {}
    deleted["source_fetch_logs"] = (
        await session.execute(
            delete(SourceFetchLog).where(SourceFetchLog.fetched_at < cutoffs["source_fetch_logs"])
        )
    ).rowcount or 0
    deleted["raw_news_items"] = (
        await session.execute(
            delete(RawNewsItem).where(RawNewsItem.fetched_at < cutoffs["raw_news_items"])
        )
    ).rowcount or 0
    deleted["normalized_news_items"] = (
        await session.execute(
            delete(NormalizedNewsItem).where(
                NormalizedNewsItem.created_at < cutoffs["normalized_news_items"]
            )
        )
    ).rowcount or 0
    deleted["event_clusters"] = (
        await session.execute(
            delete(EventCluster).where(EventCluster.created_at < cutoffs["event_clusters"])
        )
    ).rowcount or 0
    deleted["alert_decisions"] = (
        await session.execute(
            delete(AlertDecisionRecord).where(
                AlertDecisionRecord.created_at < cutoffs["alert_decisions"]
            )
        )
    ).rowcount or 0
    session.add(
        RetentionJob(status="success", deleted_counts=deleted, completed_at=datetime.now(UTC))
    )
    return deleted


def import_sources_yaml(path: Path) -> list[dict[str, object]]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    sources = data.get("sources", [])
    if not isinstance(sources, list):
        raise ValueError("sources file must contain a sources list")
    return [source for source in sources if isinstance(source, dict)]
