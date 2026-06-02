from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from common import bot_commands as command_contracts

ALLOWED_COMMAND_TYPES = command_contracts.ALLOWED_COMMAND_TYPES
validate_command_payload = command_contracts.validate_command_payload


class BotCommandCreate(BaseModel):
    command_type: str
    payload: dict[str, Any] = Field(default_factory=dict)
    requested_by: str | None = Field(default=None, max_length=255)

    @model_validator(mode="after")
    def check_payload(self) -> BotCommandCreate:
        validate_command_payload(self.command_type, self.payload)
        return self


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
