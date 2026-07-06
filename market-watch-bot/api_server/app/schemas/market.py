from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class MarketMoveRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

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
    created_at: datetime | None = None
