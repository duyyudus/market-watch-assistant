from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator

from common.config import validate_source_type


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

    @field_validator("source_type")
    @classmethod
    def validate_supported_source_type(cls, value: str) -> str:
        return validate_source_type(value)


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

    @field_validator("source_type")
    @classmethod
    def validate_supported_source_type(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return validate_source_type(value)


class SourceBulkEnabledUpdate(BaseModel):
    enabled: bool


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
    auto_quality_score: int | None = None
    quality_metrics: dict[str, object] | None = None
    quality_calculated_at: datetime | None = None
    effective_source_score: int | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class DailySourceItemCount(BaseModel):
    date: str
    count: int


class SourceHealthRead(BaseModel):
    source_id: str
    name: str
    enabled: bool
    category: str
    region: str
    health_status: str
    latest_status: str | None = None
    last_fetched_at: datetime | None = None
    consecutive_failure_count: int
    average_latency_ms: int | None = None
    daily_item_counts: list[DailySourceItemCount]
