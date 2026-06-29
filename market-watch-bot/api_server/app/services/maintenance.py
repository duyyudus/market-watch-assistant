from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api_server.app.services.query import apply_pagination, count_for
from common.db.models import (
    EventCluster,
    EventClusterEmbedding,
    EventScoreHistory,
    JobRun,
    LLMAnalysisRun,
    MissedCatalystReview,
    NewsItemEmbedding,
    NormalizedNewsItem,
    RetentionJob,
    SourceFetchLog,
)

MODEL_PRICING_PER_1K = {
    "openai/gpt-4.1-mini": {"prompt": 0.0004, "completion": 0.0016},
    "gpt-4o": {"prompt": 0.005, "completion": 0.015},
    "gpt-4o-mini": {"prompt": 0.00015, "completion": 0.0006},
    "openai/text-embedding-3-large": {"prompt": 0.00013, "completion": 0.0},
}


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


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


async def get_llm_cost_summary(session: AsyncSession) -> dict[str, object]:
    since = datetime.now(UTC) - timedelta(days=7)
    rows = list(
        (
            await session.scalars(
                select(LLMAnalysisRun)
                .where(LLMAnalysisRun.created_at >= since)
                .order_by(LLMAnalysisRun.created_at.asc())
            )
        ).all()
    )
    daily: dict[str, dict[str, object]] = {}
    by_model: dict[str, dict[str, object]] = {}
    by_analysis_type: dict[str, dict[str, object]] = {}
    weekly = _empty_cost_bucket("last_7_days")
    for row in rows:
        usage = row.usage or {}
        prompt_tokens = _int_usage(usage, "prompt_tokens")
        completion_tokens = _int_usage(usage, "completion_tokens")
        total_tokens = _int_usage(usage, "total_tokens") or prompt_tokens + completion_tokens
        cost = _estimated_cost(row.model, prompt_tokens, completion_tokens)
        day = _as_utc(row.created_at).date().isoformat()
        _add_cost(
            daily.setdefault(day, _empty_cost_bucket(day)),
            prompt_tokens,
            completion_tokens,
            total_tokens,
            cost,
        )
        _add_cost(weekly, prompt_tokens, completion_tokens, total_tokens, cost)
        model_bucket = by_model.setdefault(
            row.model,
            _empty_breakdown(model=row.model),
        )
        _add_cost(model_bucket, prompt_tokens, completion_tokens, total_tokens, cost)
        type_bucket = by_analysis_type.setdefault(
            row.target_type,
            _empty_breakdown(analysis_type=row.target_type),
        )
        _add_cost(type_bucket, prompt_tokens, completion_tokens, total_tokens, cost)
    return {
        "daily": list(daily.values()),
        "weekly": weekly,
        "by_model": list(by_model.values()),
        "by_analysis_type": list(by_analysis_type.values()),
    }


async def list_pipeline_metrics(
    session: AsyncSession,
    *,
    limit: int,
    offset: int,
) -> tuple[list[dict[str, object]], int]:
    stmt = (
        select(JobRun)
        .where(JobRun.job_name == "pipeline")
        .order_by(JobRun.started_at.desc())
    )
    total = await count_for(session, stmt)
    rows = list((await session.scalars(apply_pagination(stmt, limit=limit, offset=offset))).all())
    items: list[dict[str, object]] = []
    for row in rows:
        result = row.result or {}
        metrics = result.get("pipeline_metrics")
        if not isinstance(metrics, dict):
            continue
        items.append(
            {
                "job_run_id": row.id,
                "started_at": row.started_at,
                "completed_at": row.completed_at,
                "status": str(metrics.get("status") or row.status),
                "duration_ms": int(metrics.get("duration_ms") or 0),
                "stages": metrics.get("stages") or [],
                "slow_stages": metrics.get("slow_stages") or [],
            }
        )
    return items, total


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


def _int_usage(usage: dict[str, object], key: str) -> int:
    value = usage.get(key)
    if isinstance(value, int | float):
        return int(value)
    return 0


def _estimated_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    pricing = MODEL_PRICING_PER_1K.get(model)
    if pricing is None:
        return 0.0
    return round(
        (prompt_tokens / 1000 * pricing["prompt"])
        + (completion_tokens / 1000 * pricing["completion"]),
        6,
    )


def _empty_cost_bucket(date: str) -> dict[str, object]:
    return {
        "date": date,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "estimated_cost_usd": 0.0,
    }


def _empty_breakdown(
    *,
    model: str | None = None,
    analysis_type: str | None = None,
) -> dict[str, object]:
    return {
        "model": model,
        "analysis_type": analysis_type,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "estimated_cost_usd": 0.0,
    }


def _add_cost(
    bucket: dict[str, object],
    prompt_tokens: int,
    completion_tokens: int,
    total_tokens: int,
    cost: float,
) -> None:
    bucket["prompt_tokens"] = int(bucket["prompt_tokens"]) + prompt_tokens
    bucket["completion_tokens"] = int(bucket["completion_tokens"]) + completion_tokens
    bucket["total_tokens"] = int(bucket["total_tokens"]) + total_tokens
    bucket["estimated_cost_usd"] = round(float(bucket["estimated_cost_usd"]) + cost, 6)
