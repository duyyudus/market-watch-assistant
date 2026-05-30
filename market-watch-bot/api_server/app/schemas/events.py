from __future__ import annotations

from datetime import datetime

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
    last_updated_at: datetime | None = None
