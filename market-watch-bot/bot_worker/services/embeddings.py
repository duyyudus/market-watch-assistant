from __future__ import annotations

import asyncio
import math
from collections.abc import Callable

from sqlalchemy import delete, select
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

DB_VECTOR_DIMENSIONS = int(NewsItemEmbedding.__table__.c.vector.type.dimensions)


def validate_embedding_dimensions(config: EmbeddingConfig) -> None:
    if config.provider == "local":
        return
    if config.dimensions != DB_VECTOR_DIMENSIONS:
        raise ValueError(
            f"configured embedding dimensions {config.dimensions} do not match "
            f"database vector columns ({DB_VECTOR_DIMENSIONS}); run a vector migration "
            "before changing dimensions"
        )


def _batch_work_items[T](work_items: list[T], *, max_concurrency: int) -> list[list[T]]:
    concurrency = max(1, max_concurrency)
    batch_size = max(1, math.ceil(len(work_items) / concurrency))
    return [
        work_items[index : index + batch_size]
        for index in range(0, len(work_items), batch_size)
    ]


async def _embed_text_batches(
    text_batches: list[list[str]], *, config: EmbeddingConfig
) -> list[list[float]]:
    provider = embedding_provider(config)
    semaphore = asyncio.Semaphore(max(1, config.max_concurrency))

    async def embed_with_limit(texts: list[str]) -> list[list[float]]:
        async with semaphore:
            return await provider.embed(texts)

    batch_vectors = await asyncio.gather(*(embed_with_limit(texts) for texts in text_batches))
    return [vector for vectors in batch_vectors for vector in vectors]


async def embed_pending_news_items(
    session: AsyncSession, *, config: EmbeddingConfig, limit: int | None = None
) -> int:
    validate_embedding_dimensions(config)
    existing = select(NewsItemEmbedding.news_item_id)
    stmt = (
        select(NormalizedNewsItem)
        .where(NormalizedNewsItem.id.not_in(existing))
        .where(NormalizedNewsItem.processing_status != "ignored")
        .order_by(NormalizedNewsItem.created_at.desc())
    )
    if limit is not None:
        stmt = stmt.limit(limit)
    items = list((await session.scalars(stmt)).all())
    if not items:
        return 0
    if config.provider != "local" and not config.api_key:
        return 0
    work_items: list[tuple[NormalizedNewsItem, str]] = []
    for item in items:
        entities = await news_item_entities(session, item.id)
        text = (
            build_embedding_text(
                title=item.title,
                snippet=item.snippet,
                source_name=item.source_name,
                entities=entities,
                region=item.region,
                asset_classes=item.asset_classes,
            )
        )
        work_items.append((item, text))
    batches = _batch_work_items(work_items, max_concurrency=config.max_concurrency)
    vectors = await _embed_text_batches(
        [[text for _item, text in batch] for batch in batches],
        config=config,
    )
    for (item, text), vector in zip(work_items, vectors, strict=True):
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


def _event_cluster_embedding_text(cluster: EventCluster) -> str:
    return build_embedding_text(
        title=cluster.canonical_headline,
        snippet=cluster.summary,
        source_name="event_cluster",
        entities=cluster.affected_entities,
        region=",".join(cluster.regions),
        asset_classes=cluster.asset_classes,
    )


async def embed_event_clusters(
    session: AsyncSession,
    clusters: list[EventCluster],
    *,
    config: EmbeddingConfig,
    progress: Callable[[str, int, int], None] | None = None,
) -> int:
    """Recompute embeddings for several clusters in place using compute-then-swap.

    Texts are embedded in concurrent batches (``config.max_concurrency``), then the new
    vectors are written and the stale rows removed only after every vector is computed, so
    no cluster is left without an embedding (which would make it invisible to live vector
    attach). When the provider cannot embed (missing API key) the stale rows are dropped
    instead, since a vector built from now-outdated cluster text would match the wrong
    items. Returns the number of fresh vectors written.
    """
    validate_embedding_dimensions(config)
    cluster_ids = [cluster.id for cluster in clusters]
    if not cluster_ids:
        return 0
    if config.provider != "local" and not config.api_key:
        await session.execute(
            delete(EventClusterEmbedding).where(
                EventClusterEmbedding.event_cluster_id.in_(cluster_ids)
            )
        )
        return 0
    work_items = [(cluster, _event_cluster_embedding_text(cluster)) for cluster in clusters]
    batches = _batch_work_items(work_items, max_concurrency=config.max_concurrency)
    vectors = await _embed_text_batches(
        [[text for _cluster, text in batch] for batch in batches],
        config=config,
    )
    await session.execute(
        delete(EventClusterEmbedding).where(
            EventClusterEmbedding.event_cluster_id.in_(cluster_ids)
        )
    )
    for (cluster, text), vector in zip(work_items, vectors, strict=True):
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
    if progress is not None:
        progress("embedding", len(work_items), len(work_items))
    return len(work_items)


async def embed_event_cluster(
    session: AsyncSession, cluster: EventCluster, *, config: EmbeddingConfig
) -> bool:
    """Recompute one cluster's embedding in place (compute-then-swap).

    Thin wrapper over :func:`embed_event_clusters` for the single-cluster live-attach
    path. Returns True when a fresh vector was written.
    """
    return await embed_event_clusters(session, [cluster], config=config) > 0


async def embed_pending_event_clusters(
    session: AsyncSession, *, config: EmbeddingConfig, limit: int | None = None
) -> int:
    validate_embedding_dimensions(config)
    existing = select(EventClusterEmbedding.event_cluster_id)
    stmt = (
        select(EventCluster)
        .where(EventCluster.id.not_in(existing))
        .order_by(EventCluster.created_at.desc())
    )
    if limit is not None:
        stmt = stmt.limit(limit)
    clusters = list((await session.scalars(stmt)).all())
    if not clusters:
        return 0
    if config.provider != "local" and not config.api_key:
        return 0
    work_items = [(cluster, _event_cluster_embedding_text(cluster)) for cluster in clusters]
    batches = _batch_work_items(work_items, max_concurrency=config.max_concurrency)
    vectors = await _embed_text_batches(
        [[text for _cluster, text in batch] for batch in batches],
        config=config,
    )
    for (cluster, text), vector in zip(work_items, vectors, strict=True):
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
