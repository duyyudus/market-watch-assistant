from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


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
