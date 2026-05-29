from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl

ALLOWED_COMMAND_TYPES = {
    "pipeline.run",
    "source.fetch",
    "alert.dispatch",
    "event.rescore",
    "event.mark",
    "event.recluster",
    "investigation.run_event",
    "retention.preview",
    "retention.run",
}


class ListEnvelope[T](BaseModel):
    items: list[T]
    total: int


class SourceBase(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    url: HttpUrl
    region: str = Field(min_length=1, max_length=64)
    category: str = Field(min_length=1, max_length=64)
    source_type: str = Field(default="rss", min_length=1, max_length=32)
    language: str = Field(default="en", min_length=1, max_length=16)
    source_score: int = Field(default=60, ge=0, le=100)
    polling_interval_seconds: int = Field(default=300, ge=60, le=86400)
    enabled: bool = True


class SourceCreate(SourceBase):
    pass


class SourceUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    url: HttpUrl | None = None
    region: str | None = Field(default=None, min_length=1, max_length=64)
    category: str | None = Field(default=None, min_length=1, max_length=64)
    source_type: str | None = Field(default=None, min_length=1, max_length=32)
    language: str | None = Field(default=None, min_length=1, max_length=16)
    source_score: int | None = Field(default=None, ge=0, le=100)
    polling_interval_seconds: int | None = Field(default=None, ge=60, le=86400)
    enabled: bool | None = None


class SourceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    source_type: str
    category: str
    region: str
    asset_classes: list[str]
    url: str
    language: str
    enabled: bool
    polling_interval_seconds: int
    source_score: int
    created_at: datetime | None = None
    updated_at: datetime | None = None


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
    last_updated_at: datetime | None = None


class NewsRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    source_id: str
    title: str
    snippet: str | None = None
    url: str
    canonical_url: str | None = None
    source_name: str
    source_type: str
    source_score: int
    published_at: datetime | None = None
    fetched_at: datetime | None = None
    language: str
    region: str
    asset_classes: list[str]
    processing_status: str
    is_paywalled: bool
    full_text_available: bool


class EntityRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    entity_type: str
    raw_text: str
    normalized_name: str
    ticker: str | None = None
    exchange: str | None = None
    country: str | None = None
    confidence: int


class AlertRead(BaseModel):
    id: str
    event_cluster_id: str
    decision: str
    reason: str
    score_breakdown: dict[str, Any]
    sent_at: datetime | None = None
    channel: str | None = None
    suppression_reason: str | None = None
    created_at: datetime | None = None
    event: dict[str, Any] | None = None
    latest_delivery_status: str | None = None
    latest_delivery_error: str | None = None


class JobRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    job_name: str
    status: str
    started_at: datetime | None = None
    completed_at: datetime | None = None
    result: dict[str, Any] | None = None
    error_message: str | None = None


class WatchlistCreate(BaseModel):
    symbol: str | None = Field(default=None, max_length=64)
    name: str = Field(min_length=1, max_length=255)
    entity_type: str = Field(min_length=1, max_length=32)
    tier: str = Field(default="D", pattern="^[SABCD]$")
    region: str | None = Field(default=None, max_length=64)
    asset_class: str | None = Field(default=None, max_length=64)
    aliases: list[str] = Field(default_factory=list)
    enabled: bool = True


class WatchlistUpdate(BaseModel):
    symbol: str | None = Field(default=None, max_length=64)
    name: str | None = Field(default=None, min_length=1, max_length=255)
    entity_type: str | None = Field(default=None, min_length=1, max_length=32)
    tier: str | None = Field(default=None, pattern="^[SABCD]$")
    region: str | None = Field(default=None, max_length=64)
    asset_class: str | None = Field(default=None, max_length=64)
    aliases: list[str] | None = None
    enabled: bool | None = None


class WatchlistRead(WatchlistCreate):
    model_config = ConfigDict(from_attributes=True)

    id: str
    created_at: datetime | None = None
    updated_at: datetime | None = None


class AlertPolicy(BaseModel):
    immediate_threshold: int = Field(default=80, ge=0, le=100)
    watchlist_threshold: int = Field(default=55, ge=0, le=100)
    digest_threshold: int = Field(default=30, ge=0, le=100)
    default_channel: str = Field(default="log", min_length=1, max_length=32)


class BotCommandCreate(BaseModel):
    command_type: str
    payload: dict[str, Any] = Field(default_factory=dict)
    requested_by: str | None = Field(default=None, max_length=255)


class BotCommandRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    command_type: str
    status: Literal["pending", "running", "succeeded", "failed", "cancelled"]
    payload: dict[str, Any]
    result: dict[str, Any] | None = None
    error_message: str | None = None
    requested_by: str | None = None
    created_at: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
