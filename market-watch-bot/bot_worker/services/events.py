from __future__ import annotations

from datetime import timedelta

from sqlalchemy import delete, select
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
    VectorClusterCandidate,
    cluster_candidates,
    is_vector_cluster_attachable,
    vector_similarity_score,
)
from bot_worker.scoring import AlertThresholds, ScoreInput, decide_alert, score_event
from bot_worker.services.watchlists import news_item_entities, watchlist_entries
from bot_worker.watchlist import match_watchlist


def pgvector_literal(vector: list[float]) -> str:
    return "[" + ",".join(str(float(value)) for value in vector) + "]"
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
    cluster.regions = sorted(set(cluster.regions) | {item.region})
    cluster.asset_classes = sorted(set(cluster.asset_classes) | set(item.asset_classes))
    cluster.affected_entities = sorted(set(cluster.affected_entities) | set(entities))
    cluster.source_count += 1
    cluster.top_source_score = max(cluster.top_source_score, item.source_score)
    _rescore_cluster(cluster)
    await session.execute(
        delete(EventClusterEmbedding).where(EventClusterEmbedding.event_cluster_id == cluster.id)
    )
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
        matches = match_watchlist(f"{item.title} {item.snippet or ''}", watch_entries)
        entities = [match.name for match in matches] or item.title.split()[:3]
        stored_entities = await news_item_entities(session, item.id)
        if stored_entities:
            entities = stored_entities
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
                    similarity=vector_candidate.similarity,
                )
                attached = True
                break
        if attached:
            continue
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
