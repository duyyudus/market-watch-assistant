from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class WatchlistCreate(BaseModel):
    symbol: str | None = Field(default=None, max_length=64)
    name: str = Field(min_length=1, max_length=255)
    entity_type: str = Field(min_length=1, max_length=32)
    tier: str = Field(default="D", pattern="^[SABCD]$")
    region: str | None = Field(default=None, max_length=64)
    asset_class: str | None = Field(default=None, max_length=64)
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
    region: str | None = Field(default=None, max_length=64)
    asset_class: str | None = Field(default=None, max_length=64)
    aliases: list[str] | None = None
    enabled: bool | None = None

    @field_validator("tier", mode="before")
    @classmethod
    def normalize_tier(cls, value: str | None) -> str | None:
        return value.upper() if value is not None else None


class WatchlistRead(WatchlistCreate):
    model_config = ConfigDict(from_attributes=True)

    id: str
    created_at: datetime | None = None
    updated_at: datetime | None = None
