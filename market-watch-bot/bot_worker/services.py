from __future__ import annotations

import logging
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from time import perf_counter

import httpx
import yaml
from sqlalchemy import Select, delete, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from bot_worker.catalysts import best_market_move_score_for_event
from bot_worker.config import STARTER_SOURCES, StarterSource
from bot_worker.db.models import (
    AlertDecisionRecord,
    EventCluster,
    EventClusterEmbedding,
    EventClusterItem,
    EventScoreHistory,
    JobRun,
    MarketMove,
    MissedCatalystReview,
    NewsEntity,
    NewsItemEmbedding,
    NewsSource,
    NormalizedNewsItem,
    RawNewsItem,
    RetentionJob,
    SourceFetchLog,
    WatchlistEntity,
    utcnow,
)
from bot_worker.embeddings import (
    EmbeddingConfig,
    build_embedding_text,
    embedding_provider,
    embedding_text_hash,
)
from bot_worker.events import EventCandidate, cluster_candidates
from bot_worker.market_data import (
    MarketMoveDraft,
    parse_binance_ticker_move,
    parse_coingecko_market_move,
    parse_vietnam_quote_moves,
    parse_yahoo_chart_move,
    score_market_move,
)
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

logger = logging.getLogger("bot_worker")

CORE_JOBS = [
    "poll_sources",
    "normalize_raw_items",
    "dedupe_news_items",
    "extract_entities",
    "generate_embeddings",
    "cluster_events",
    "fetch_market_moves",
    "score_events",
    "dispatch_alerts",
    "build_digest",
    "run_missed_catalyst_review",
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


def is_rss_item_fresh(
    *,
    published_at: datetime | None,
    fetched_at: datetime,
    now: datetime,
    freshness_hours: int,
) -> bool:
    effective_time = published_at or fetched_at
    if effective_time.tzinfo is None:
        effective_time = effective_time.replace(tzinfo=UTC)
    return effective_time >= now - timedelta(hours=freshness_hours)


def digest_time_in_window(
    *,
    published_at: datetime | None,
    fetched_at: datetime | None,
    created_at: datetime,
    since: datetime,
    until: datetime,
) -> bool:
    effective_time = published_at or fetched_at or created_at
    if effective_time.tzinfo is None:
        effective_time = effective_time.replace(tzinfo=UTC)
    return since <= effective_time < until


def select_digest_headline(
    *,
    canonical_headline: str,
    members: list[tuple[str, datetime | None, datetime | None, datetime]],
    since: datetime,
    until: datetime,
) -> str:
    in_window: list[tuple[str, datetime]] = []
    for title, published_at, fetched_at, created_at in members:
        effective_time = published_at or fetched_at or created_at
        if effective_time.tzinfo is None:
            effective_time = effective_time.replace(tzinfo=UTC)
        if since <= effective_time < until:
            in_window.append((title, effective_time))
    if not in_window:
        return canonical_headline
    return max(in_window, key=lambda item: item[1])[0]


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


def _result_rowcount(result: object) -> int:
    return int(getattr(result, "rowcount", 0) or 0)


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
    score = score_event(
        ScoreInput(
            top_source_score=max(item.source_score for item in items),
            source_count=len(items),
            watchlist_tier="A" if affected_entities else None,
            is_duplicate=False,
            is_stale=cluster.status == "stale",
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


async def normalize_pending_raw_items(
    session: AsyncSession, *, limit: int = 500, freshness_hours: int = 72
) -> int:
    stmt = (
        select(RawNewsItem, NewsSource)
        .join(NewsSource, NewsSource.id == RawNewsItem.source_id)
        .outerjoin(NormalizedNewsItem, NormalizedNewsItem.raw_item_id == RawNewsItem.id)
        .where(NormalizedNewsItem.id.is_(None))
        .limit(limit)
    )
    rows = (await session.execute(stmt)).all()
    inserted = 0
    now = datetime.now(UTC)
    for raw, source in rows:
        title = normalize_text(raw.raw_title)
        if not title or not raw.raw_url:
            continue
        published_at = normalize_datetime(raw.raw_published_at)
        if not is_rss_item_fresh(
            published_at=published_at,
            fetched_at=raw.fetched_at,
            now=now,
            freshness_hours=freshness_hours,
        ):
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
            published_at=published_at,
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


async def news_item_entities(session: AsyncSession, news_item_id: str) -> list[str]:
    rows = list(
        (
            await session.scalars(
                select(NewsEntity).where(NewsEntity.news_item_id == news_item_id)
            )
        ).all()
    )
    return [row.normalized_name for row in rows]


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


async def embed_pending_news_items(
    session: AsyncSession, *, config: EmbeddingConfig, limit: int = 100
) -> int:
    existing = select(NewsItemEmbedding.news_item_id)
    stmt = (
        select(NormalizedNewsItem)
        .where(NormalizedNewsItem.id.not_in(existing))
        .where(NormalizedNewsItem.processing_status != "ignored")
        .order_by(NormalizedNewsItem.created_at.desc())
        .limit(limit)
    )
    items = list((await session.scalars(stmt)).all())
    if not items:
        return 0
    if config.provider != "local" and not config.api_key:
        return 0
    texts: list[str] = []
    for item in items:
        entities = await news_item_entities(session, item.id)
        texts.append(
            build_embedding_text(
                title=item.title,
                snippet=item.snippet,
                source_name=item.source_name,
                entities=entities,
                region=item.region,
                asset_classes=item.asset_classes,
            )
        )
    vectors = await embedding_provider(config).embed(texts)
    for item, text, vector in zip(items, texts, vectors, strict=True):
        session.add(
            NewsItemEmbedding(
                news_item_id=item.id,
                provider=config.provider,
                embedding_model=config.model,
                embedding_version=config.version,
                dimensions=config.dimensions,
                embedding_text_hash=embedding_text_hash(text),
                vector=vector,
            )
        )
    return len(vectors)


async def embed_pending_event_clusters(
    session: AsyncSession, *, config: EmbeddingConfig, limit: int = 100
) -> int:
    existing = select(EventClusterEmbedding.event_cluster_id)
    stmt = (
        select(EventCluster)
        .where(EventCluster.id.not_in(existing))
        .order_by(EventCluster.created_at.desc())
        .limit(limit)
    )
    clusters = list((await session.scalars(stmt)).all())
    if not clusters:
        return 0
    if config.provider != "local" and not config.api_key:
        return 0
    texts = [
        build_embedding_text(
            title=cluster.canonical_headline,
            snippet=cluster.summary,
            source_name="event_cluster",
            entities=cluster.affected_entities,
            region=",".join(cluster.regions),
            asset_classes=cluster.asset_classes,
        )
        for cluster in clusters
    ]
    vectors = await embedding_provider(config).embed(texts)
    for cluster, text, vector in zip(clusters, texts, vectors, strict=True):
        session.add(
            EventClusterEmbedding(
                event_cluster_id=cluster.id,
                provider=config.provider,
                embedding_model=config.model,
                embedding_version=config.version,
                dimensions=config.dimensions,
                embedding_text_hash=embedding_text_hash(text),
                vector=vector,
            )
        )
    return len(vectors)


async def store_market_moves(session: AsyncSession, moves: list[MarketMoveDraft]) -> int:
    for move in moves:
        session.add(
            MarketMove(
                asset_symbol=move.asset_symbol,
                asset_class=move.asset_class,
                exchange=move.exchange,
                timestamp=move.timestamp,
                window=move.window,
                price_change_pct=move.price_change_pct,
                volume_change_pct=move.volume_change_pct,
                value_traded_change_pct=move.value_traded_change_pct,
                z_score=move.z_score,
            )
        )
    return len(moves)


async def fetch_market_moves(
    *,
    symbols: list[str],
    window: str,
    vn_base_url: str,
    symbol_map: dict[str, str] | None = None,
) -> list[MarketMoveDraft]:
    symbol_map = symbol_map or {}
    global_symbol_set = {"SPY", "QQQ", "DIA", "GLD", "SLV", "USO", "DXY", "TNX"}
    crypto_symbols = [
        symbol.upper()
        for symbol in symbols
        if symbol.upper().endswith("USDT") or symbol.upper() in {"BTC", "ETH", "SOL"}
    ]
    global_symbols = [
        symbol.upper()
        for symbol in symbols
        if symbol.upper() in global_symbol_set or "." in symbol or symbol.upper().endswith(".US")
    ]
    routed = {*crypto_symbols, *global_symbols}
    vn_symbols = [symbol.lower() for symbol in symbols if symbol.upper() not in routed]
    moves: list[MarketMoveDraft] = []
    async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
        for symbol in crypto_symbols:
            if symbol.endswith("USDT"):
                try:
                    response = await client.get(
                        "https://api.binance.com/api/v3/ticker/24hr", params={"symbol": symbol}
                    )
                    response.raise_for_status()
                    moves.append(parse_binance_ticker_move(response.json(), window=window))
                    continue
                except httpx.HTTPError:
                    pass
            coin_id = symbol_map.get(symbol.removesuffix("USDT"), symbol.lower())
            response = await client.get(
                "https://api.coingecko.com/api/v3/coins/markets",
                params={
                    "vs_currency": "usd",
                    "ids": coin_id,
                    "price_change_percentage": "24h",
                },
            )
            response.raise_for_status()
            moves.append(parse_coingecko_market_move(response.json(), symbol=symbol, window=window))
        for symbol in global_symbols:
            yahoo_symbol = symbol_map.get(symbol, symbol)
            response = await client.get(
                f"https://query2.finance.yahoo.com/v8/finance/chart/{yahoo_symbol}",
                params={"range": "5d", "interval": "1d"},
                headers={"User-Agent": "Mozilla/5.0"},
            )
            response.raise_for_status()
            moves.append(
                parse_yahoo_chart_move(
                    response.json(),
                    symbol=symbol,
                    asset_class="equity",
                    window=window,
                )
            )
        if vn_symbols:
            response = await client.post(
                f"{vn_base_url.rstrip('/')}/api/v1/stocks/quotes",
                json={"symbols": vn_symbols},
                headers={"accept": "application/json"},
            )
            response.raise_for_status()
            moves.extend(parse_vietnam_quote_moves(response.json()))
    return moves


async def run_missed_catalyst_review(session: AsyncSession, *, window: str = "1d") -> int:
    existing_reviews = select(MissedCatalystReview.asset_symbol).where(
        MissedCatalystReview.move_window == window
    )
    moves = list(
        (
            await session.scalars(
                select(MarketMove)
                .where(MarketMove.window == window)
                .where(MarketMove.asset_symbol.not_in(existing_reviews))
            )
        ).all()
    )
    count = 0
    for move in moves:
        move_score = score_market_move(
            price_change_pct=move.price_change_pct,
            volume_change_pct=move.volume_change_pct,
            z_score=move.z_score,
        )
        if move_score < 70:
            continue
        matched = await session.scalar(
            select(EventCluster).where(
                EventCluster.created_at >= move.timestamp - timedelta(hours=24),
                EventCluster.created_at <= move.timestamp + timedelta(hours=24),
                or_(
                    EventCluster.affected_tickers.contains([move.asset_symbol]),
                    EventCluster.affected_entities.contains([move.asset_symbol]),
                ),
            )
        )
        session.add(
            MissedCatalystReview(
                asset_symbol=move.asset_symbol,
                asset_class=move.asset_class,
                move_window=move.window,
                price_change_pct=move.price_change_pct,
                volume_change_pct=move.volume_change_pct,
                detected_event_cluster_id=matched.id if matched else None,
                status="resolved" if matched else "pending",
            )
        )
        count += 1
    return count


async def market_move_score_for_cluster(session: AsyncSession, cluster: EventCluster) -> int:
    rows = list(
        (
            await session.scalars(
                select(MarketMove).where(
                    MarketMove.timestamp >= cluster.created_at - timedelta(hours=24),
                    MarketMove.timestamp <= cluster.created_at + timedelta(hours=24),
                )
            )
        ).all()
    )
    moves = [
        MarketMoveDraft(
            asset_symbol=row.asset_symbol,
            asset_class=row.asset_class,
            exchange=row.exchange,
            timestamp=row.timestamp,
            window=row.window,
            price_change_pct=row.price_change_pct,
            volume_change_pct=row.volume_change_pct,
            value_traded_change_pct=row.value_traded_change_pct,
            z_score=row.z_score,
        )
        for row in rows
    ]
    return best_market_move_score_for_event(
        affected_tickers=cluster.affected_tickers,
        affected_entities=cluster.affected_entities,
        event_time=cluster.created_at,
        moves=moves,
        tolerance=timedelta(hours=24),
    )


async def record_alert_decisions(session: AsyncSession) -> int:
    stmt = (
        select(EventCluster)
        .outerjoin(AlertDecisionRecord, AlertDecisionRecord.event_cluster_id == EventCluster.id)
        .where(AlertDecisionRecord.id.is_(None))
    )
    clusters = list((await session.scalars(stmt)).all())
    count = 0
    for cluster in clusters:
        move_score = await market_move_score_for_cluster(session, cluster)
        score = score_event(
            ScoreInput(
                top_source_score=cluster.top_source_score,
                source_count=cluster.source_count,
                watchlist_tier="A" if cluster.affected_entities else None,
                is_duplicate=False,
                is_stale=cluster.status == "stale",
                status=cluster.status,
                market_move_score=move_score,
            )
        )
        cluster.confirmation_score = score.confidence_score
        cluster.novelty_score = score.novelty_score
        cluster.urgency_score = score.urgency_score
        cluster.market_impact_score = max(score.impact_score, score.market_move_score)
        cluster.relevance_score = score.relevance_score
        cluster.final_score = score.final_score
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


async def run_pipeline(
    session: AsyncSession,
    *,
    dry_run: bool = False,
    freshness_hours: int = 72,
    embedding_config: EmbeddingConfig | None = None,
) -> dict[str, int | str]:
    if dry_run:
        return {"status": "dry_run", "jobs": len(CORE_JOBS)}

    logger.info("======================================================================")
    logger.info(
        "🚀 Starting pipeline run [freshness_hours=%d, embeddings=%s]",
        freshness_hours,
        "enabled" if embedding_config is not None else "disabled",
    )
    logger.info("======================================================================")

    sources = list(
        (await session.scalars(select(NewsSource).where(NewsSource.enabled.is_(True)))).all()
    )
    fetched = 0
    logger.info("─── [Stage 1/7] Polling News Sources ───")
    logger.info("  Found %d enabled news sources to poll", len(sources))
    for source in sources:
        logger.info("  → Polling source: %s (%s)", source.name, source.url)
        result = await fetch_source(session, source)
        if result.get("status") == "success":
            inserted = int(result.get("inserted", 0))
            fetched += inserted
            logger.info(
                "  ✓ Successfully fetched %d items from %s (inserted %d new)",
                result.get("items", 0),
                source.name,
                inserted,
            )
        else:
            logger.error("  ❌ Failed to fetch source %s: %s", source.name, result.get("error"))

    logger.info("─── [Stage 2/7] Normalizing Raw Items ───")
    normalized = await normalize_pending_raw_items(session, freshness_hours=freshness_hours)
    logger.info("  ✓ Normalized %d news items", normalized)

    logger.info("─── [Stage 3/7] Deduplicating News Items ───")
    duplicates = await mark_exact_duplicates(session)
    logger.info("  ✓ Marked %d duplicate news items", duplicates)

    news_embeddings = 0
    logger.info("─── [Stage 4/7] Generating News Embeddings ───")
    if embedding_config is not None:
        news_embeddings = await embed_pending_news_items(session, config=embedding_config)
        logger.info("  ✓ Generated embeddings for %d news items", news_embeddings)
    else:
        logger.info("  ⚠ Embedding config not provided, skipping news embedding generation")

    logger.info("─── [Stage 5/7] Building Event Clusters ───")
    clusters = await build_event_clusters(session)
    logger.info("  ✓ Built %d new event clusters", clusters)

    event_embeddings = 0
    logger.info("─── [Stage 6/7] Generating Event Embeddings ───")
    if embedding_config is not None:
        event_embeddings = await embed_pending_event_clusters(session, config=embedding_config)
        logger.info("  ✓ Generated embeddings for %d event clusters", event_embeddings)
    else:
        logger.info(
            "  ⚠ Embedding config not provided, skipping event cluster embedding generation"
        )

    logger.info("─── [Stage 7/7] Recording Alert Decisions ───")
    alerts = await record_alert_decisions(session)
    logger.info("  ✓ Recorded alert decisions for %d event clusters", alerts)

    logger.info("======================================================================")
    logger.info("🎉 Pipeline run completed successfully!")
    logger.info("======================================================================")
    return {
        "fetched": fetched,
        "normalized": normalized,
        "duplicates": duplicates,
        "news_embeddings": news_embeddings,
        "clusters": clusters,
        "event_embeddings": event_embeddings,
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


async def digest_preview(
    session: AsyncSession,
    *,
    limit: int = 20,
    since: datetime | None = None,
    until: datetime | None = None,
) -> list[EventCluster]:
    stmt = (
        select(EventCluster)
        .order_by(EventCluster.final_score.desc(), EventCluster.created_at.desc())
        .limit(limit)
    )
    if since is not None or until is not None:
        item_time = func.coalesce(
            NormalizedNewsItem.published_at,
            NormalizedNewsItem.fetched_at,
            NormalizedNewsItem.created_at,
        )
        matching_clusters = (
            select(EventClusterItem.event_cluster_id)
            .join(NormalizedNewsItem, NormalizedNewsItem.id == EventClusterItem.news_item_id)
            .distinct()
        )
        if since is not None:
            matching_clusters = matching_clusters.where(item_time >= since)
        if until is not None:
            matching_clusters = matching_clusters.where(item_time < until)
        stmt = stmt.where(EventCluster.id.in_(matching_clusters))
    return list((await session.scalars(stmt)).all())


async def digest_display_headline(
    session: AsyncSession,
    event: EventCluster,
    *,
    since: datetime | None,
    until: datetime | None,
) -> str:
    if since is None or until is None:
        return event.canonical_headline
    rows = list(
        (
            await session.execute(
                select(
                    NormalizedNewsItem.title,
                    NormalizedNewsItem.published_at,
                    NormalizedNewsItem.fetched_at,
                    NormalizedNewsItem.created_at,
                )
                .join(EventClusterItem, EventClusterItem.news_item_id == NormalizedNewsItem.id)
                .where(EventClusterItem.event_cluster_id == event.id)
            )
        ).all()
    )
    return select_digest_headline(
        canonical_headline=event.canonical_headline,
        members=[
            (title, published_at, fetched_at, created_at)
            for title, published_at, fetched_at, created_at in rows
        ],
        since=since,
        until=until,
    )


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
