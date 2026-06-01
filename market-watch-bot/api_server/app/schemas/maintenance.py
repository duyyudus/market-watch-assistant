from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class FetchLogRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    source_id: str
    fetched_at: datetime
    status: str
    http_status: int | None = None
    error_message: str | None = None
    item_count: int | None = None
    duration_ms: int
    content_hash: str | None = None


class ScoreHistoryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    event_cluster_id: str
    score_breakdown: dict[str, object]
    final_score: int
    created_at: datetime


class CatalystReviewRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    asset_symbol: str
    asset_class: str
    move_window: str
    price_change_pct: float
    volume_change_pct: float | None = None
    detected_event_cluster_id: str | None = None
    status: str
    agent_summary: str | None = None
    created_at: datetime
    updated_at: datetime | None = None


class EmbeddingStats(BaseModel):
    total_news_items: int
    news_items_with_embeddings: int
    embedding_coverage_pct: float
    total_event_clusters: int
    event_clusters_with_embeddings: int
    cluster_embedding_coverage_pct: float
    news_providers: list[str]
    news_models: list[str]
    cluster_providers: list[str]
    cluster_models: list[str]


class LLMRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    target_type: str
    target_id: str
    provider: str
    model: str
    prompt_version: str
    prompt_hash: str
    input_snapshot: dict[str, object]
    result: dict[str, object] | None = None
    status: str
    error_message: str | None = None
    usage: dict[str, object] | None = None
    created_at: datetime
    updated_at: datetime | None = None


class LLMCostBucket(BaseModel):
    date: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    estimated_cost_usd: float


class LLMCostBreakdown(BaseModel):
    model: str | None = None
    analysis_type: str | None = None
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    estimated_cost_usd: float


class LLMCostSummary(BaseModel):
    daily: list[LLMCostBucket]
    weekly: LLMCostBucket
    by_model: list[LLMCostBreakdown]
    by_analysis_type: list[LLMCostBreakdown]


class PipelineStageMetricRead(BaseModel):
    stage_name: str
    start_time: str | None = None
    end_time: str | None = None
    duration_ms: int
    items_in: int | None = None
    items_out: int | None = None
    status: str


class SlowPipelineStageRead(BaseModel):
    stage_name: str
    duration_ms: int
    average_duration_ms: int
    threshold_ms: int


class PipelineMetricsRead(BaseModel):
    job_run_id: str
    started_at: datetime | None = None
    completed_at: datetime | None = None
    status: str
    duration_ms: int
    stages: list[PipelineStageMetricRead]
    slow_stages: list[SlowPipelineStageRead]


class RetentionJobRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    status: str
    deleted_counts: dict[str, int]
    started_at: datetime
    completed_at: datetime | None = None
