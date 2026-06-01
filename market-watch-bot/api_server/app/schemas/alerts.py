from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class AlertRead(BaseModel):
    id: str
    event_cluster_id: str
    decision: str
    reason: str
    score_breakdown: dict[str, Any]
    sent_at: datetime | None = None
    channel: str | None = None
    suppression_reason: str | None = None
    acknowledged_at: datetime | None = None
    created_at: datetime | None = None
    event: dict[str, Any] | None = None
    latest_delivery_status: str | None = None
    latest_delivery_error: str | None = None


class AlertChannelBase(BaseModel):
    name: str
    channel_type: str
    config: dict[str, Any] = {}
    enabled: bool = True
    is_default: bool = False


class AlertChannelCreate(AlertChannelBase):
    pass


class AlertChannelUpdate(BaseModel):
    name: str | None = None
    channel_type: str | None = None
    config: dict[str, Any] | None = None
    enabled: bool | None = None
    is_default: bool | None = None


class AlertChannelRead(AlertChannelBase):
    id: str
    created_at: datetime | None = None
    updated_at: datetime | None = None


class AlertChannelTestPayload(BaseModel):
    message: str = "Market watch alert delivery test."


class AlertSuppressionRuleBase(BaseModel):
    name: str
    rule_type: str
    config: dict[str, Any] = {}
    enabled: bool = True


class AlertSuppressionRuleCreate(AlertSuppressionRuleBase):
    pass


class AlertSuppressionRuleUpdate(BaseModel):
    name: str | None = None
    rule_type: str | None = None
    config: dict[str, Any] | None = None
    enabled: bool | None = None


class AlertSuppressionRuleRead(AlertSuppressionRuleBase):
    id: str
    created_at: datetime | None = None
    updated_at: datetime | None = None
