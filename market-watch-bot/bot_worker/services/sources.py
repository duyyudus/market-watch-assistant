from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from time import perf_counter

import httpx
import yaml
from sqlalchemy import Select, delete, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from bot_worker.config import STARTER_SOURCES, Settings, StarterSource
from bot_worker.db.models import (
    AlertDecisionRecord,
    AppSetting,
    EventCluster,
    EventClusterEmbedding,
    EventClusterItem,
    EventScoreHistory,
    MissedCatalystReview,
    NewsEntity,
    NewsItemEmbedding,
    NewsSource,
    NormalizedNewsItem,
    RawNewsItem,
    SourceFetchLog,
)
from bot_worker.normalize import (
    content_hash,
)
from bot_worker.rss import parse_rss_items
from bot_worker.scoring import AlertThresholds, ScoreInput, decide_alert, score_event
from bot_worker.services.common import _json_safe, _published_to_string, _result_rowcount
from bot_worker.services.external_providers import PROVIDER_RETRY_POLICIES, request_with_retry
from bot_worker.services.watchlists import tier_for_entities, watchlist_entries


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
async def seed_starter_sources(session: AsyncSession) -> int:
    changed = 0
    for source in STARTER_SOURCES:
        existing = await session.scalar(select(NewsSource).where(NewsSource.name == source.name))
        if existing is not None:
            before = (
                existing.url,
                existing.region,
                existing.category,
                existing.source_type,
                existing.language,
                existing.source_score,
                existing.polling_interval_seconds,
            )
            existing.url = source.url
            existing.region = source.region
            existing.category = source.category
            existing.source_type = source.source_type
            existing.language = source.language
            existing.source_score = source.source_score
            existing.polling_interval_seconds = source.polling_interval_seconds
            existing.parser_type = "rss"
            existing.asset_classes = [source.category]
            after = (
                existing.url,
                existing.region,
                existing.category,
                existing.source_type,
                existing.language,
                existing.source_score,
                existing.polling_interval_seconds,
            )
            changed += int(before != after)
            continue
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
        changed += result.rowcount or 0
    return changed


async def seed_configuration_presets(session: AsyncSession, settings: Settings) -> bool:
    value = settings.configuration_presets.model_dump()
    existing = await session.get(AppSetting, "configuration_presets")
    if existing is None:
        session.add(AppSetting(key="configuration_presets", value=value))
        return True
    if existing.value == value:
        return False
    existing.value = value
    return True


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
async def _refresh_event_cluster_after_source_purge(session: AsyncSession, cluster_id: str) -> bool:
    cluster = await session.get(EventCluster, cluster_id)
    if cluster is None:
        return False
    items = list(
        (
            await session.scalars(
                select(NormalizedNewsItem)
                .join(EventClusterItem, EventClusterItem.news_item_id == NormalizedNewsItem.id)
                .where(EventClusterItem.event_cluster_id == cluster_id)
            )
        ).all()
    )
    if not items:
        return False

    item_ids = [item.id for item in items]
    entity_rows = list(
        (
            await session.execute(
                select(NewsEntity.normalized_name, NewsEntity.ticker).where(
                    NewsEntity.news_item_id.in_(item_ids)
                )
            )
        ).all()
    )
    latest = max(items, key=lambda item: item.published_at or item.fetched_at or item.created_at)
    affected_entities = sorted({name for name, _ticker in entity_rows if name})
    affected_tickers = sorted({ticker for _name, ticker in entity_rows if ticker})
    if not affected_entities:
        affected_entities = sorted(cluster.affected_entities)
    if not affected_tickers:
        affected_tickers = sorted(cluster.affected_tickers)
    watch_entries = await watchlist_entries(session)
    score = score_event(
        ScoreInput(
            top_source_score=max(item.source_score for item in items),
            source_count=len(items),
            watchlist_tier=tier_for_entities(
                entities=affected_entities,
                tickers=affected_tickers,
                entries=watch_entries,
            ),
            is_duplicate=False,
            is_stale=cluster.status == "stale",
            unique_high_quality_source_count=sum(1 for item in items if item.source_score >= 75),
            status=cluster.status,
        )
    )

    cluster.canonical_headline = latest.title
    cluster.last_updated_at = max(item.fetched_at for item in items)
    cluster.regions = sorted({item.region for item in items})
    cluster.asset_classes = sorted(
        {asset_class for item in items for asset_class in item.asset_classes}
    )
    cluster.affected_entities = affected_entities
    cluster.affected_tickers = affected_tickers
    cluster.source_count = len(items)
    cluster.high_quality_source_count = sum(1 for item in items if item.source_score >= 75)
    cluster.top_source_score = max(item.source_score for item in items)
    cluster.confirmation_score = score.confidence_score
    cluster.novelty_score = score.novelty_score
    cluster.urgency_score = score.urgency_score
    cluster.market_impact_score = score.impact_score
    cluster.relevance_score = score.relevance_score
    cluster.final_score = score.final_score
    cluster.alert_level = decide_alert(score.final_score, AlertThresholds()).decision
    return True
async def purge_source(session: AsyncSession, identifier: str) -> dict[str, int | str]:
    source = await get_source(session, identifier)
    if source is None:
        return {"status": "not_found", "source": identifier}

    source_id = source.id
    source_name = source.name
    news_item_ids = list(
        (
            await session.scalars(
                select(NormalizedNewsItem.id).where(NormalizedNewsItem.source_id == source_id)
            )
        ).all()
    )
    raw_item_ids = list(
        (
            await session.scalars(select(RawNewsItem.id).where(RawNewsItem.source_id == source_id))
        ).all()
    )
    cluster_ids = []
    if news_item_ids:
        cluster_ids = list(
            (
                await session.scalars(
                    select(EventClusterItem.event_cluster_id)
                    .where(EventClusterItem.news_item_id.in_(news_item_ids))
                    .distinct()
                )
            ).all()
        )

    deleted = {
        "source_fetch_logs": 0,
        "news_item_embeddings": 0,
        "news_entities": 0,
        "event_cluster_items": 0,
        "normalized_news_items": 0,
        "raw_news_items": 0,
        "missed_catalyst_reviews_updated": 0,
        "alert_decisions": 0,
        "event_score_history": 0,
        "event_cluster_embeddings": 0,
        "event_clusters": 0,
        "refreshed_event_clusters": 0,
        "news_sources": 0,
    }

    deleted["source_fetch_logs"] = _result_rowcount(
        await session.execute(delete(SourceFetchLog).where(SourceFetchLog.source_id == source_id))
    )
    if news_item_ids:
        deleted["news_item_embeddings"] = _result_rowcount(
            await session.execute(
                delete(NewsItemEmbedding).where(NewsItemEmbedding.news_item_id.in_(news_item_ids))
            )
        )
        deleted["news_entities"] = _result_rowcount(
            await session.execute(
                delete(NewsEntity).where(NewsEntity.news_item_id.in_(news_item_ids))
            )
        )
        deleted["event_cluster_items"] = _result_rowcount(
            await session.execute(
                delete(EventClusterItem).where(EventClusterItem.news_item_id.in_(news_item_ids))
            )
        )
        deleted["normalized_news_items"] = _result_rowcount(
            await session.execute(
                delete(NormalizedNewsItem).where(NormalizedNewsItem.id.in_(news_item_ids))
            )
        )
    if raw_item_ids:
        deleted["raw_news_items"] = _result_rowcount(
            await session.execute(delete(RawNewsItem).where(RawNewsItem.id.in_(raw_item_ids)))
        )

    orphan_cluster_ids: list[str] = []
    if cluster_ids:
        orphan_cluster_ids = list(
            (
                await session.scalars(
                    select(EventCluster.id).where(
                        EventCluster.id.in_(cluster_ids),
                        EventCluster.id.not_in(select(EventClusterItem.event_cluster_id)),
                    )
                )
            ).all()
        )
        if orphan_cluster_ids:
            deleted["missed_catalyst_reviews_updated"] = _result_rowcount(
                await session.execute(
                    update(MissedCatalystReview)
                    .where(MissedCatalystReview.detected_event_cluster_id.in_(orphan_cluster_ids))
                    .values(detected_event_cluster_id=None)
                )
            )
            deleted["alert_decisions"] = _result_rowcount(
                await session.execute(
                    delete(AlertDecisionRecord).where(
                        AlertDecisionRecord.event_cluster_id.in_(orphan_cluster_ids)
                    )
                )
            )
            deleted["event_score_history"] = _result_rowcount(
                await session.execute(
                    delete(EventScoreHistory).where(
                        EventScoreHistory.event_cluster_id.in_(orphan_cluster_ids)
                    )
                )
            )
            deleted["event_cluster_embeddings"] = _result_rowcount(
                await session.execute(
                    delete(EventClusterEmbedding).where(
                        EventClusterEmbedding.event_cluster_id.in_(orphan_cluster_ids)
                    )
                )
            )
            deleted["event_clusters"] = _result_rowcount(
                await session.execute(
                    delete(EventCluster).where(EventCluster.id.in_(orphan_cluster_ids))
                )
            )
        remaining_cluster_ids = [
            cluster_id for cluster_id in cluster_ids if cluster_id not in orphan_cluster_ids
        ]
        if remaining_cluster_ids:
            deleted["event_cluster_embeddings"] += _result_rowcount(
                await session.execute(
                    delete(EventClusterEmbedding).where(
                        EventClusterEmbedding.event_cluster_id.in_(remaining_cluster_ids)
                    )
                )
            )
        for cluster_id in remaining_cluster_ids:
            if await _refresh_event_cluster_after_source_purge(session, cluster_id):
                deleted["refreshed_event_clusters"] += 1

    deleted["news_sources"] = _result_rowcount(
        await session.execute(delete(NewsSource).where(NewsSource.id == source_id))
    )
    return {"status": "purged", "source": source_name, **deleted}
def effective_source_score(source: NewsSource) -> int:
    auto_score = getattr(source, "auto_quality_score", None)
    if auto_score is None:
        return int(source.source_score)
    return round(int(source.source_score) * 0.7 + int(auto_score) * 0.3)


async def compute_source_quality(
    session: AsyncSession,
    source: NewsSource,
    *,
    now: datetime | None = None,
) -> tuple[int, dict[str, int]]:
    current = now or datetime.now(UTC)
    since = current - timedelta(days=30)
    fetch_total = int(
        await session.scalar(
            select(func.count())
            .select_from(SourceFetchLog)
            .where(SourceFetchLog.source_id == source.id, SourceFetchLog.fetched_at >= since)
        )
        or 0
    )
    fetch_success = int(
        await session.scalar(
            select(func.count())
            .select_from(SourceFetchLog)
            .where(
                SourceFetchLog.source_id == source.id,
                SourceFetchLog.fetched_at >= since,
                SourceFetchLog.status == "success",
            )
        )
        or 0
    )
    news_total = int(
        await session.scalar(
            select(func.count())
            .select_from(NormalizedNewsItem)
            .where(
                NormalizedNewsItem.source_id == source.id,
                NormalizedNewsItem.created_at >= since,
            )
        )
        or 0
    )
    deduped = int(
        await session.scalar(
            select(func.count())
            .select_from(NormalizedNewsItem)
            .where(
                NormalizedNewsItem.source_id == source.id,
                NormalizedNewsItem.created_at >= since,
                NormalizedNewsItem.processing_status == "deduped",
            )
        )
        or 0
    )
    clustered = int(
        await session.scalar(
            select(func.count())
            .select_from(EventClusterItem)
            .join(NormalizedNewsItem, NormalizedNewsItem.id == EventClusterItem.news_item_id)
            .where(
                NormalizedNewsItem.source_id == source.id,
                NormalizedNewsItem.created_at >= since,
            )
        )
        or 0
    )
    reliability = round((fetch_success / fetch_total) * 100) if fetch_total else 60
    duplicate_rate = round((deduped / news_total) * 100) if news_total else 0
    event_contribution = round((clustered / news_total) * 100) if news_total else 0
    metrics = {
        "reliability": reliability,
        "duplicate_rate": duplicate_rate,
        "event_contribution": event_contribution,
    }
    score = round(
        reliability * 0.50
        + (100 - duplicate_rate) * 0.20
        + event_contribution * 0.30
    )
    return min(100, max(0, score)), metrics


async def refresh_source_quality_scores(session: AsyncSession) -> dict[str, int]:
    sources = await list_sources(session)
    updated = 0
    for source in sources:
        score, metrics = await compute_source_quality(session, source)
        source.auto_quality_score = score
        source.quality_metrics = metrics
        source.quality_calculated_at = datetime.now(UTC)
        updated += 1
    return {"sources_updated": updated}


async def fetch_source_content(source: NewsSource) -> tuple[int, str, dict[str, str]]:
    headers = {}
    if getattr(source, "etag", None):
        headers["If-None-Match"] = source.etag
    if getattr(source, "last_modified", None):
        headers["If-Modified-Since"] = source.last_modified
    async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
        response = await request_with_retry(
            provider="rss",
            method="GET",
            url=source.url,
            retry_policy=PROVIDER_RETRY_POLICIES["rss"],
            client=client,
            headers=headers or None,
        )
        return response.status_code, response.text, dict(response.headers)
async def fetch_source(session: AsyncSession, source: NewsSource) -> dict[str, int | str]:
    started = perf_counter()
    try:
        decision = should_poll_source(source)
        if not decision.should_poll:
            return {"status": "skipped", "reason": decision.reason}
        http_status, body, headers = await fetch_source_content(source)
        if http_status == 304:
            session.add(
                SourceFetchLog(
                    source_id=source.id,
                    status="success",
                    http_status=http_status,
                    item_count=0,
                    duration_ms=round((perf_counter() - started) * 1000),
                )
            )
            mark_source_fetch_result(source, status="success", inserted=0)
            return {"status": "not_modified", "items": 0, "inserted": 0}
        if headers.get("etag"):
            source.etag = headers["etag"]
        if headers.get("last-modified"):
            source.last_modified = headers["last-modified"]
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
        mark_source_fetch_result(source, status="success", inserted=inserted)
        return {"status": "success", "items": len(items), "inserted": inserted}
    except Exception as exc:  # noqa: BLE001 - command should persist source diagnostics
        mark_source_fetch_result(source, status="failed", inserted=0)
        session.add(
            SourceFetchLog(
                source_id=source.id,
                status="failed",
                error_message=str(exc),
                duration_ms=round((perf_counter() - started) * 1000),
            )
        )
        return {"status": "failed", "error": str(exc)}
def import_sources_yaml(path: Path) -> list[dict[str, object]]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    sources = data.get("sources", [])
    if not isinstance(sources, list):
        raise ValueError("sources file must contain a sources list")
    return [source for source in sources if isinstance(source, dict)]
@dataclass(frozen=True)
class SourcePollingDecision:
    should_poll: bool
    reason: str


BURST_POLLING_INTERVAL_SECONDS = 60
BURST_WINDOW = timedelta(minutes=30)
FAILURE_COOLDOWN = timedelta(minutes=30)


def _ensure_aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


def should_poll_source(source: NewsSource, *, now: datetime | None = None) -> SourcePollingDecision:
    current = now or datetime.now(UTC)
    disabled_until = _ensure_aware(getattr(source, "disabled_until_at", None))
    if disabled_until is not None and disabled_until > current:
        return SourcePollingDecision(False, "failure_cooldown")
    last_fetched_at = _ensure_aware(getattr(source, "last_fetched_at", None))
    if last_fetched_at is None:
        return SourcePollingDecision(True, "never_fetched")
    burst_until = _ensure_aware(getattr(source, "burst_until_at", None))
    interval = (
        BURST_POLLING_INTERVAL_SECONDS
        if burst_until is not None and burst_until > current
        else source.polling_interval_seconds
    )
    if current - last_fetched_at < timedelta(seconds=interval):
        return SourcePollingDecision(False, "interval_not_elapsed")
    return SourcePollingDecision(True, "due")


def mark_source_fetch_result(
    source: NewsSource,
    *,
    now: datetime | None = None,
    status: str,
    inserted: int,
) -> None:
    current = now or datetime.now(UTC)
    source.last_fetched_at = current
    if status == "success":
        source.consecutive_failure_count = 0
        source.disabled_until_at = None
        if inserted > 0:
            source.burst_until_at = current + BURST_WINDOW
        return
    source.consecutive_failure_count = int(getattr(source, "consecutive_failure_count", 0) or 0) + 1
    if source.consecutive_failure_count >= 3:
        source.disabled_until_at = current + FAILURE_COOLDOWN
