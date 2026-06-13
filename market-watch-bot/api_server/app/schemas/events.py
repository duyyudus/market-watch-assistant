from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class EventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    canonical_headline: str
    summary: str | None = None
    status: str
    regions: list[str]
    asset_classes: list[str]
    affected_entities: list[str]
    affected_tickers: list[str]
    source_count: int
    top_source_score: int
    confirmation_score: int
    novelty_score: int
    urgency_score: int
    market_impact_score: int
    relevance_score: int
    final_score: int
    alert_level: str | None = None
    first_seen_at: datetime | None = None
    report_start_at: datetime | None = None
    report_end_at: datetime | None = None
    last_updated_at: datetime | None = None


class EventTimelineItem(BaseModel):
    news_item_id: str
    title: str
    source_name: str
    source_score: int
    url: str
    published_at: datetime | None = None
    fetched_at: datetime | None = None
    added_at: datetime | None = None
    relation_type: str
    similarity_score: int | None = None
    decision_metadata: dict[str, Any] | None = None


class EventMarketMoveRead(BaseModel):
    id: str
    asset_symbol: str
    asset_class: str
    exchange: str | None = None
    timestamp: datetime
    window: str
    price_change_pct: float
    volume_change_pct: float | None = None
    value_traded_change_pct: float | None = None
    z_score: float | None = None


class EventLLMRunRead(BaseModel):
    id: str
    provider: str
    model: str
    prompt_version: str
    result: dict[str, Any] | None = None
    status: str
    error_message: str | None = None
    usage: dict[str, Any] | None = None
    created_at: datetime
    updated_at: datetime | None = None


class EventDetailRead(EventRead):
    latest_alert: dict[str, Any] | None = None
    latest_investigation: dict[str, Any] | None = None
    score_history: list[dict[str, Any]]
    timeline: list[EventTimelineItem]
    llm_runs: list[EventLLMRunRead]
    market_moves: list[EventMarketMoveRead]
