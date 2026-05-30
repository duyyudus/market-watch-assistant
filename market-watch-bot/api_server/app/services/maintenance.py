from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api_server.app.services.query import apply_pagination, count_for
from common.db.models import (
    EventCluster,
    EventClusterEmbedding,
    EventScoreHistory,
    LLMAnalysisRun,
    MissedCatalystReview,
    NewsItemEmbedding,
    NormalizedNewsItem,
    RetentionJob,
    SourceFetchLog,
)


async def list_source_fetch_logs(
    session: AsyncSession,
    *,
    limit: int,
    offset: int,
    status: str | None = None,
    source_id: str | None = None,
) -> tuple[list[SourceFetchLog], int]:
    stmt = select(SourceFetchLog).order_by(SourceFetchLog.fetched_at.desc())
    if status:
        stmt = stmt.where(SourceFetchLog.status == status)
    if source_id:
        stmt = stmt.where(SourceFetchLog.source_id == source_id)

    total = await count_for(session, stmt)
    rows = list((await session.scalars(apply_pagination(stmt, limit=limit, offset=offset))).all())
    return rows, total


async def list_event_score_history(
    session: AsyncSession,
    *,
    limit: int,
    offset: int,
    event_id: str | None = None,
) -> tuple[list[EventScoreHistory], int]:
    stmt = select(EventScoreHistory).order_by(EventScoreHistory.created_at.desc())
    if event_id:
        stmt = stmt.where(EventScoreHistory.event_cluster_id == event_id)

    total = await count_for(session, stmt)
    rows = list((await session.scalars(apply_pagination(stmt, limit=limit, offset=offset))).all())
    return rows, total


async def list_missed_catalysts(
    session: AsyncSession,
    *,
    limit: int,
    offset: int,
    status: str | None = None,
) -> tuple[list[MissedCatalystReview], int]:
    stmt = select(MissedCatalystReview).order_by(MissedCatalystReview.created_at.desc())
    if status:
        stmt = stmt.where(MissedCatalystReview.status == status)

    total = await count_for(session, stmt)
    rows = list((await session.scalars(apply_pagination(stmt, limit=limit, offset=offset))).all())
    return rows, total


async def get_embedding_stats(session: AsyncSession) -> dict[str, object]:
    # Total counts
    total_news = int(
        await session.scalar(select(func.count(NormalizedNewsItem.id))) or 0
    )
    news_embedded = int(
        await session.scalar(
            select(func.count(NewsItemEmbedding.news_item_id))
        ) or 0
    )
    
    total_clusters = int(
        await session.scalar(select(func.count(EventCluster.id))) or 0
    )
    clusters_embedded = int(
        await session.scalar(
            select(func.count(EventClusterEmbedding.event_cluster_id))
        ) or 0
    )

    # Coverage
    news_cov = (news_embedded / total_news * 100.0) if total_news > 0 else 0.0
    cluster_cov = (clusters_embedded / total_clusters * 100.0) if total_clusters > 0 else 0.0

    # Providers and models
    news_p_stmt = select(NewsItemEmbedding.provider).distinct()
    news_providers = list((await session.scalars(news_p_stmt)).all())
    
    news_m_stmt = select(NewsItemEmbedding.embedding_model).distinct()
    news_models = list((await session.scalars(news_m_stmt)).all())
    
    cluster_p_stmt = select(EventClusterEmbedding.provider).distinct()
    cluster_providers = list((await session.scalars(cluster_p_stmt)).all())
    
    cluster_m_stmt = select(EventClusterEmbedding.embedding_model).distinct()
    cluster_models = list((await session.scalars(cluster_m_stmt)).all())

    return {
        "total_news_items": total_news,
        "news_items_with_embeddings": news_embedded,
        "embedding_coverage_pct": news_cov,
        "total_event_clusters": total_clusters,
        "event_clusters_with_embeddings": clusters_embedded,
        "cluster_embedding_coverage_pct": cluster_cov,
        "news_providers": [p for p in news_providers if p],
        "news_models": [m for m in news_models if m],
        "cluster_providers": [p for p in cluster_providers if p],
        "cluster_models": [m for m in cluster_models if m],
    }


async def list_llm_runs(
    session: AsyncSession,
    *,
    limit: int,
    offset: int,
    status: str | None = None,
    target_type: str | None = None,
) -> tuple[list[LLMAnalysisRun], int]:
    stmt = select(LLMAnalysisRun).order_by(LLMAnalysisRun.created_at.desc())
    if status:
        stmt = stmt.where(LLMAnalysisRun.status == status)
    if target_type:
        stmt = stmt.where(LLMAnalysisRun.target_type == target_type)

    total = await count_for(session, stmt)
    rows = list((await session.scalars(apply_pagination(stmt, limit=limit, offset=offset))).all())
    return rows, total


async def list_retention_jobs(
    session: AsyncSession,
    *,
    limit: int,
    offset: int,
) -> tuple[list[RetentionJob], int]:
    stmt = select(RetentionJob).order_by(RetentionJob.started_at.desc())

    total = await count_for(session, stmt)
    rows = list((await session.scalars(apply_pagination(stmt, limit=limit, offset=offset))).all())
    return rows, total
