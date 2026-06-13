from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class WatchlistCreate(BaseModel):
    symbol: str | None = Field(default=None, max_length=64)
    name: str = Field(min_length=1, max_length=255)
    entity_type: str = Field(min_length=1, max_length=32)
    tier: str = Field(default="D", pattern="^[SABCD]$")
    region: str = Field(min_length=1, max_length=64)
    asset_class: str = Field(min_length=1, max_length=64)
    aliases: list[str] = Field(default_factory=list)
    enabled: bool = True

    @field_validator("tier", mode="before")
    @classmethod
    def normalize_tier(cls, value: str) -> str:
        return value.upper()


class WatchlistUpdate(BaseModel):
    symbol: str | None = Field(default=None, max_length=64)
    name: str | None = Field(default=None, min_length=1, max_length=255)
    entity_type: str | None = Field(default=None, min_length=1, max_length=32)
    tier: str | None = Field(default=None, pattern="^[SABCD]$")
    region: str | None = Field(default=None, min_length=1, max_length=64)
    asset_class: str | None = Field(default=None, min_length=1, max_length=64)
    aliases: list[str] | None = None
    enabled: bool | None = None

    @field_validator("tier", mode="before")
    @classmethod
    def normalize_tier(cls, value: str | None) -> str | None:
        return value.upper() if value is not None else None

    @model_validator(mode="after")
    def reject_null_required_fields(self) -> WatchlistUpdate:
        # region/asset_class are non-nullable on the entity; an explicit null in a
        # PATCH body must be rejected rather than silently nulling the column.
        for field in ("region", "asset_class"):
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f"{field} cannot be set to null")
        return self


class MarketDataResolutionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    status: str
    provider: str | None = None
    provider_symbol: str | None = None
    reason: str | None = None
    resolved_at: datetime | None = None


class WatchlistRead(WatchlistCreate):
    model_config = ConfigDict(from_attributes=True)

    id: str
    created_at: datetime | None = None
    updated_at: datetime | None = None
    market_data_resolution: MarketDataResolutionRead | None = None
