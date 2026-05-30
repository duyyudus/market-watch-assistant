from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

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
