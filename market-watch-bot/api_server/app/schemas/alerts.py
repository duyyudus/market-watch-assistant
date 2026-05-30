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
    created_at: datetime | None = None
    event: dict[str, Any] | None = None
    latest_delivery_status: str | None = None
    latest_delivery_error: str | None = None
