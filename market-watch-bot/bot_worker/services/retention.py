from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import delete, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot_worker.db.models import (
    AgentInvestigation,
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
    NewsEntity,
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
    AgentInvestigation,
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


def _stale_agent_investigation_filter(cutoff: datetime):
    event_exists = exists(
        select(EventCluster.id).where(EventCluster.id == AgentInvestigation.target_id)
    )
    move_exists = exists(select(MarketMove.id).where(MarketMove.id == AgentInvestigation.target_id))
    review_exists = exists(
        select(MissedCatalystReview.id).where(
            MissedCatalystReview.id == AgentInvestigation.target_id
        )
    )
    return or_(
        AgentInvestigation.created_at < cutoff,
        (AgentInvestigation.target_type == "event_cluster") & ~event_exists,
        (AgentInvestigation.target_type == "market_move") & ~move_exists,
        (AgentInvestigation.target_type == "missed_catalyst_review") & ~review_exists,
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
    counts["agent_investigations"] = (
        await session.scalar(
            select(func.count())
            .select_from(AgentInvestigation)
            .where(_stale_agent_investigation_filter(cutoffs["event_clusters"]))
        )
        or 0
    )
    return counts


async def run_retention(session: AsyncSession, policy: RetentionPolicy) -> dict[str, int]:
    cutoffs = retention_cutoffs(datetime.now(UTC), policy)
    deleted: dict[str, int] = {}
    stale_news_ids = select(NormalizedNewsItem.id).where(
        NormalizedNewsItem.created_at < cutoffs["normalized_news_items"]
    )
    stale_cluster_ids = select(EventCluster.id).where(
        EventCluster.created_at < cutoffs["event_clusters"]
    )
    stale_alert_ids = select(AlertDecisionRecord.id).where(
        AlertDecisionRecord.created_at < cutoffs["alert_decisions"]
    )
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
    deleted["alert_deliveries"] = (
        await session.execute(
            delete(AlertDeliveryRecord).where(AlertDeliveryRecord.alert_decision_id.in_(stale_alert_ids))
        )
    ).rowcount or 0
    deleted["alert_decisions"] = (
        await session.execute(
            delete(AlertDecisionRecord).where(
                AlertDecisionRecord.created_at < cutoffs["alert_decisions"]
            )
        )
    ).rowcount or 0
    deleted["event_score_history"] = (
        await session.execute(
            delete(EventScoreHistory).where(EventScoreHistory.event_cluster_id.in_(stale_cluster_ids))
        )
    ).rowcount or 0
    deleted["event_cluster_embeddings"] = (
        await session.execute(
            delete(EventClusterEmbedding).where(
                EventClusterEmbedding.event_cluster_id.in_(stale_cluster_ids)
            )
        )
    ).rowcount or 0
    deleted["agent_investigations"] = (
        await session.execute(
            delete(AgentInvestigation).where(
                _stale_agent_investigation_filter(cutoffs["event_clusters"])
            )
        )
    ).rowcount or 0
    deleted["missed_catalyst_reviews_updated"] = (
        await session.execute(
            delete(MissedCatalystReview).where(
                MissedCatalystReview.detected_event_cluster_id.in_(stale_cluster_ids)
            )
        )
    ).rowcount or 0
    deleted["event_cluster_items"] = (
        await session.execute(
            delete(EventClusterItem).where(EventClusterItem.event_cluster_id.in_(stale_cluster_ids))
        )
    ).rowcount or 0
    deleted["news_entities"] = (
        await session.execute(delete(NewsEntity).where(NewsEntity.news_item_id.in_(stale_news_ids)))
    ).rowcount or 0
    deleted["news_item_embeddings"] = (
        await session.execute(
            delete(NewsItemEmbedding).where(NewsItemEmbedding.news_item_id.in_(stale_news_ids))
        )
    ).rowcount or 0
    deleted["event_cluster_items_for_news"] = (
        await session.execute(
            delete(EventClusterItem).where(EventClusterItem.news_item_id.in_(stale_news_ids))
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
