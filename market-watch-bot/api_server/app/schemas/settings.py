from __future__ import annotations

from typing import Any
from pydantic import BaseModel, Field


class AlertPolicy(BaseModel):
    immediate_threshold: int = Field(default=80, ge=0, le=100)
    watchlist_threshold: int = Field(default=55, ge=0, le=100)
    digest_threshold: int = Field(default=30, ge=0, le=100)
    default_channel: str = Field(default="log", min_length=1, max_length=32)


class SourcePresets(BaseModel):
    source_types: list[str]
    regions: list[str]
    categories: list[str]
    languages: list[str]


class WatchlistPresets(BaseModel):
    entity_types: list[str]
    tiers: list[str]
    regions: list[str]
    asset_classes: list[str]


class AlertChannelPreset(BaseModel):
    type: str
    placeholder: str
    template: dict[str, Any]
    description: str
    parameters: dict[str, str]


class AlertSuppressionPreset(BaseModel):
    type: str
    placeholder: str
    template: dict[str, Any]
    description: str
    parameters: dict[str, str]


class AlertPresets(BaseModel):
    channels: list[AlertChannelPreset]
    rules: list[AlertSuppressionPreset]


class ConfigurationPresets(BaseModel):
    sources: SourcePresets
    watchlist: WatchlistPresets
    alerts: AlertPresets
