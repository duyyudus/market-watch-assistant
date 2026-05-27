from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot_worker.db.models import (
    AlertDecisionRecord,
    AlertDeliveryRecord,
    EventCluster,
    EventClusterEmbedding,
    EventClusterItem,
    EventScoreHistory,
    JobRun,
    LLMAnalysisRun,
    MarketMove,
    MissedCatalystReview,
    NewsItemEmbedding,
    NormalizedNewsItem,
    RawNewsItem,
    RetentionJob,
    SourceFetchLog,
)
from bot_worker.retention import RetentionPolicy, retention_cutoffs

BASELINE_RESET_TARGET_MODELS = (
    AlertDeliveryRecord,
    AlertDecisionRecord,
    EventScoreHistory,
    EventClusterEmbedding,
    EventClusterItem,
    MissedCatalystReview,
    EventCluster,
    NewsItemEmbedding,
    LLMAnalysisRun,
    MarketMove,
    SourceFetchLog,
    JobRun,
    RetentionJob,
)
BASELINE_RESET_TARGET_TABLES = tuple(model.__tablename__ for model in BASELINE_RESET_TARGET_MODELS)


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


async def baseline_reset_preview(session: AsyncSession) -> dict[str, int]:
    counts: dict[str, int] = {}
    for model in BASELINE_RESET_TARGET_MODELS:
        counts[model.__tablename__] = (
            await session.scalar(select(func.count()).select_from(model))
        ) or 0
    return counts


async def run_baseline_reset(session: AsyncSession) -> dict[str, int]:
    deleted: dict[str, int] = {}
    for model in BASELINE_RESET_TARGET_MODELS:
        result = await session.execute(delete(model))
        deleted[model.__tablename__] = result.rowcount or 0
    return deleted
