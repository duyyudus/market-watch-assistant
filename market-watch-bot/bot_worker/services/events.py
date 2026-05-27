from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy import text as sql_text
from sqlalchemy.ext.asyncio import AsyncSession

from bot_worker.db.models import (
    EventCluster,
    EventClusterEmbedding,
    EventClusterItem,
    NewsItemEmbedding,
    NormalizedNewsItem,
    utcnow,
)
from bot_worker.embeddings import (
    EmbeddingConfig,
)
from bot_worker.events import (
    EventCandidate,
    EventClusterDraft,
    VectorClusterCandidate,
    cluster_candidates,
    is_vector_cluster_attachable,
    vector_similarity_score,
)
from bot_worker.scoring import AlertThresholds, ScoreInput, decide_alert, score_event
from bot_worker.services.watchlists import news_item_entities, news_item_tickers, watchlist_entries
from bot_worker.watchlist import WatchlistEntry, match_watchlist


def pgvector_literal(vector: list[float]) -> str:
    return "[" + ",".join(str(float(value)) for value in vector) + "]"


def _result_rowcount(result: object) -> int:
    return int(getattr(result, "rowcount", 0) or 0)


async def vector_cluster_candidates_for_item(
    session: AsyncSession,
    news_item: NormalizedNewsItem,
    *,
    config: EmbeddingConfig,
    lookback_days: int,
    limit: int,
) -> list[VectorClusterCandidate]:
    embedding = await session.get(NewsItemEmbedding, news_item.id)
    if embedding is None:
        return []

    cutoff = utcnow() - timedelta(days=lookback_days)
    stmt = sql_text(
        """
        SELECT
            ec.id AS cluster_id,
            1 - (ece.vector <=> CAST(:query_vector AS vector)) AS similarity,
            ec.regions AS regions,
            ec.asset_classes AS asset_classes,
            ec.affected_entities AS affected_entities
        FROM event_cluster_embeddings ece
        JOIN event_clusters ec ON ec.id = ece.event_cluster_id
        WHERE ec.last_updated_at >= :cutoff
          AND ece.provider = :provider
          AND ece.embedding_model = :model
          AND ece.embedding_version = :version
          AND ece.dimensions = :dimensions
        ORDER BY ece.vector <=> CAST(:query_vector AS vector)
        LIMIT :limit
        """
    )
    rows = (
        await session.execute(
            stmt,
            {
                "query_vector": pgvector_literal(embedding.vector),
                "cutoff": cutoff,
                "provider": config.provider,
                "model": config.model,
                "version": config.version,
                "dimensions": config.dimensions,
                "limit": limit,
            },
        )
    ).all()
    candidates: list[VectorClusterCandidate] = []
    for row in rows:
        values = row._mapping
        candidates.append(
            VectorClusterCandidate(
                cluster_id=values["cluster_id"],
                similarity=float(values["similarity"]),
                regions=list(values["regions"] or []),
                asset_classes=list(values["asset_classes"] or []),
                affected_entities=list(values["affected_entities"] or []),
            )
        )
    return candidates


def _effective_news_time() -> object:
    return func.coalesce(
        NormalizedNewsItem.published_at,
        NormalizedNewsItem.fetched_at,
        NormalizedNewsItem.created_at,
    )


def _rescore_cluster(cluster: EventCluster) -> None:
    score = score_event(
        ScoreInput(
            top_source_score=cluster.top_source_score,
            source_count=cluster.source_count,
            watchlist_tier="A" if cluster.affected_entities else None,
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
async def _attach_news_item_to_cluster(
    session: AsyncSession,
    *,
    item: NormalizedNewsItem,
    cluster: EventCluster,
    entities: list[str],
    tickers: list[str],
    similarity: float,
) -> None:
    session.add(
        EventClusterItem(
            event_cluster_id=cluster.id,
            news_item_id=item.id,
            similarity_score=vector_similarity_score(similarity),
        )
    )
    cluster.last_updated_at = utcnow()
    cluster.regions = sorted(set(cluster.regions or []) | {item.region})
    cluster.asset_classes = sorted(set(cluster.asset_classes or []) | set(item.asset_classes))
    cluster.affected_entities = sorted(set(cluster.affected_entities or []) | set(entities))
    cluster.affected_tickers = sorted(set(cluster.affected_tickers or []) | set(tickers))
    cluster.source_count += 1
    cluster.top_source_score = max(cluster.top_source_score, item.source_score)
    _rescore_cluster(cluster)
    await session.execute(
        delete(EventClusterEmbedding).where(EventClusterEmbedding.event_cluster_id == cluster.id)
    )


async def _candidate_from_item(
    session: AsyncSession,
    item: NormalizedNewsItem,
    watch_entries: list[WatchlistEntry],
) -> EventCandidate:
    matches = match_watchlist(f"{item.title} {item.snippet or ''}", watch_entries)
    stored_entities = await news_item_entities(session, item.id)
    stored_tickers = await news_item_tickers(session, item.id)
    return EventCandidate(
        news_id=item.id,
        title=item.title,
        source_score=item.source_score,
        entities=stored_entities or [match.name for match in matches],
        tickers=stored_tickers or [match.symbol for match in matches if match.symbol],
        region=item.region,
        asset_classes=item.asset_classes,
        published_at=item.published_at,
    )


def _update_cluster_from_draft(cluster: EventCluster, draft: EventClusterDraft) -> None:
    cluster.canonical_headline = draft.canonical_headline
    cluster.first_seen_at = cluster.first_seen_at or utcnow()
    cluster.last_updated_at = utcnow()
    cluster.status = "reported"
    cluster.regions = sorted(draft.regions)
    cluster.asset_classes = sorted(draft.asset_classes)
    cluster.affected_entities = sorted(draft.entities)
    cluster.affected_tickers = sorted(draft.tickers)
    cluster.source_count = draft.source_count
    cluster.top_source_score = draft.top_source_score
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


def _mark_cluster_stale(cluster: EventCluster) -> None:
    cluster.status = "stale"
    cluster.last_updated_at = utcnow()
    cluster.affected_entities = []
    cluster.affected_tickers = []
    cluster.source_count = 0
    cluster.top_source_score = 0
    cluster.confirmation_score = 0
    cluster.novelty_score = 0
    cluster.urgency_score = 0
    cluster.market_impact_score = 0
    cluster.relevance_score = 0
    cluster.final_score = 0
    cluster.alert_level = None


async def recluster_recent_event_clusters(
    session: AsyncSession,
    *,
    since: datetime,
    dry_run: bool = True,
    limit: int = 500,
) -> dict[str, int | str]:
    cluster_ids = list(
        (
            await session.scalars(
                select(EventCluster.id)
                .where(EventCluster.last_updated_at >= since)
                .order_by(EventCluster.last_updated_at.desc())
                .limit(limit)
            )
        ).all()
    )
    if not cluster_ids:
        return {
            "status": "dry_run" if dry_run else "reclustered",
            "affected_clusters": 0,
            "news_items": 0,
            "new_clusters": 0,
            "stale_clusters": 0,
            "event_cluster_items_deleted": 0,
            "event_cluster_embeddings_deleted": 0,
        }

    clusters = list(
        (
            await session.scalars(
                select(EventCluster)
                .where(EventCluster.id.in_(cluster_ids))
                .order_by(EventCluster.last_updated_at.desc())
            )
        ).all()
    )
    items = list(
        (
            await session.scalars(
                select(NormalizedNewsItem)
                .join(EventClusterItem, EventClusterItem.news_item_id == NormalizedNewsItem.id)
                .where(EventClusterItem.event_cluster_id.in_(cluster_ids))
                .order_by(_effective_news_time())
            )
        ).all()
    )
    if not items:
        return {
            "status": "dry_run" if dry_run else "reclustered",
            "affected_clusters": len(cluster_ids),
            "news_items": 0,
            "new_clusters": 0,
            "stale_clusters": 0,
            "event_cluster_items_deleted": 0,
            "event_cluster_embeddings_deleted": 0,
        }

    watch_entries = await watchlist_entries(session)
    candidates = [
        await _candidate_from_item(session, item, watch_entries)
        for item in items
    ]
    drafts = cluster_candidates(candidates)
    stale_clusters = max(0, len(clusters) - len(drafts))
    if dry_run:
        return {
            "status": "dry_run",
            "affected_clusters": len(cluster_ids),
            "news_items": len(items),
            "new_clusters": len(drafts),
            "stale_clusters": stale_clusters,
            "event_cluster_items_deleted": 0,
            "event_cluster_embeddings_deleted": 0,
        }

    items_deleted = _result_rowcount(
        await session.execute(
            delete(EventClusterItem).where(EventClusterItem.event_cluster_id.in_(cluster_ids))
        )
    )
    embeddings_deleted = _result_rowcount(
        await session.execute(
            delete(EventClusterEmbedding).where(
                EventClusterEmbedding.event_cluster_id.in_(cluster_ids)
            )
        )
    )
    for cluster, draft in zip(clusters, drafts, strict=False):
        _update_cluster_from_draft(cluster, draft)
        for news_id in draft.news_ids:
            session.add(EventClusterItem(event_cluster_id=cluster.id, news_item_id=news_id))
    for cluster in clusters[len(drafts) :]:
        _mark_cluster_stale(cluster)

    return {
        "status": "reclustered",
        "affected_clusters": len(cluster_ids),
        "news_items": len(items),
        "new_clusters": len(drafts),
        "stale_clusters": stale_clusters,
        "event_cluster_items_deleted": items_deleted,
        "event_cluster_embeddings_deleted": embeddings_deleted,
    }


async def build_event_clusters(
    session: AsyncSession,
    *,
    limit: int = 500,
    embedding_config: EmbeddingConfig | None = None,
) -> int:
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
        candidate = await _candidate_from_item(session, item, watch_entries)
        entities = candidate.entities
        tickers = candidate.tickers
        attached = False
        if embedding_config is not None and embedding_config.cluster_attach_enabled:
            vector_candidates = await vector_cluster_candidates_for_item(
                session,
                item,
                config=embedding_config,
                lookback_days=embedding_config.cluster_attach_lookback_days,
                limit=embedding_config.cluster_attach_candidate_limit,
            )
            for vector_candidate in vector_candidates:
                if not is_vector_cluster_attachable(
                    vector_candidate,
                    item_region=item.region,
                    item_asset_classes=item.asset_classes,
                    item_entities=entities,
                    min_similarity=embedding_config.cluster_attach_min_similarity,
                ):
                    continue
                cluster = await session.get(EventCluster, vector_candidate.cluster_id)
                if cluster is None:
                    continue
                await _attach_news_item_to_cluster(
                    session,
                    item=item,
                    cluster=cluster,
                    entities=entities,
                    tickers=tickers,
                    similarity=vector_candidate.similarity,
                )
                attached = True
                break
        if attached:
            continue
        candidates.append(
            candidate
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
            affected_tickers=sorted(draft.tickers),
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
