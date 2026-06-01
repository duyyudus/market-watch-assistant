from __future__ import annotations

from fastapi import APIRouter, Query

from api_server.app.api.dependencies import SessionDep
from api_server.app.schemas import (
    CatalystReviewRead,
    EmbeddingStats,
    FetchLogRead,
    ListEnvelope,
    LLMCostSummary,
    LLMRunRead,
    PipelineMetricsRead,
    RetentionJobRead,
    ScoreHistoryRead,
)
from api_server.app.services import maintenance as maintenance_service

router = APIRouter(prefix="/maintenance", tags=["maintenance"])


@router.get("/fetch-logs", response_model=ListEnvelope[FetchLogRead])
async def list_fetch_logs(
    session: SessionDep,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    status: str | None = Query(None),
    source_id: str | None = Query(None),
) -> ListEnvelope[FetchLogRead]:
    rows, total = await maintenance_service.list_source_fetch_logs(
        session, limit=limit, offset=offset, status=status, source_id=source_id
    )
    return ListEnvelope(
        items=[FetchLogRead.model_validate(row) for row in rows],
        total=total,
    )


@router.get("/score-history", response_model=ListEnvelope[ScoreHistoryRead])
async def list_score_history(
    session: SessionDep,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    event_id: str | None = Query(None),
) -> ListEnvelope[ScoreHistoryRead]:
    rows, total = await maintenance_service.list_event_score_history(
        session, limit=limit, offset=offset, event_id=event_id
    )
    return ListEnvelope(
        items=[ScoreHistoryRead.model_validate(row) for row in rows],
        total=total,
    )


@router.get("/catalysts", response_model=ListEnvelope[CatalystReviewRead])
async def list_catalysts(
    session: SessionDep,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    status: str | None = Query(None),
) -> ListEnvelope[CatalystReviewRead]:
    rows, total = await maintenance_service.list_missed_catalysts(
        session, limit=limit, offset=offset, status=status
    )
    return ListEnvelope(
        items=[CatalystReviewRead.model_validate(row) for row in rows],
        total=total,
    )


@router.get("/embeddings/stats", response_model=EmbeddingStats)
async def get_embeddings_stats(session: SessionDep) -> EmbeddingStats:
    stats = await maintenance_service.get_embedding_stats(session)
    return EmbeddingStats.model_validate(stats)


@router.get("/llm-runs", response_model=ListEnvelope[LLMRunRead])
async def list_llm_runs(
    session: SessionDep,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    status: str | None = Query(None),
    target_type: str | None = Query(None),
) -> ListEnvelope[LLMRunRead]:
    rows, total = await maintenance_service.list_llm_runs(
        session, limit=limit, offset=offset, status=status, target_type=target_type
    )
    return ListEnvelope(
        items=[LLMRunRead.model_validate(row) for row in rows],
        total=total,
    )


@router.get("/llm-costs", response_model=LLMCostSummary)
async def get_llm_costs(session: SessionDep) -> LLMCostSummary:
    stats = await maintenance_service.get_llm_cost_summary(session)
    return LLMCostSummary.model_validate(stats)


@router.get("/pipeline-metrics", response_model=ListEnvelope[PipelineMetricsRead])
async def list_pipeline_metrics(
    session: SessionDep,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> ListEnvelope[PipelineMetricsRead]:
    rows, total = await maintenance_service.list_pipeline_metrics(
        session,
        limit=limit,
        offset=offset,
    )
    return ListEnvelope(
        items=[PipelineMetricsRead.model_validate(row) for row in rows],
        total=total,
    )


@router.get("/retention-jobs", response_model=ListEnvelope[RetentionJobRead])
async def list_retention_jobs(
    session: SessionDep,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> ListEnvelope[RetentionJobRead]:
    rows, total = await maintenance_service.list_retention_jobs(
        session, limit=limit, offset=offset
    )
    return ListEnvelope(
        items=[RetentionJobRead.model_validate(row) for row in rows],
        total=total,
    )
