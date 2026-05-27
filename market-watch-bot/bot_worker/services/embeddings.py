from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot_worker.db.models import (
    EventCluster,
    EventClusterEmbedding,
    NewsItemEmbedding,
    NormalizedNewsItem,
)
from bot_worker.embeddings import (
    EmbeddingConfig,
    build_embedding_text,
    embedding_provider,
    embedding_text_hash,
)
from bot_worker.services.watchlists import news_item_entities


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
