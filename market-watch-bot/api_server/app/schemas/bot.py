from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from bot_worker.services.bot_commands import ALLOWED_COMMAND_TYPES, EVENT_STATUSES

_PAYLOAD_VALIDATORS: dict[str, Any] = {
    "pipeline.run": {"optional": {"dry_run": bool}},
    "source.fetch": {"required": {"source_id": str}},
    "alert.dispatch": {"optional": {"channel": str, "limit": int, "dry_run": bool}},
    "event.rescore": {"required": {"event_id": str}},
    "event.mark": {"required": {"event_id": str, "status": str}},
    "event.recluster": {"optional": {"since": str, "limit": int, "apply": bool}},
    "investigation.run_event": {"required": {"event_id": str}},
    "retention.preview": {},
    "retention.run": {},
}


def validate_command_payload(command_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    if command_type not in ALLOWED_COMMAND_TYPES:
        raise ValueError(f"Unsupported command type: {command_type}")

    spec = _PAYLOAD_VALIDATORS[command_type]
    required = spec.get("required", {})
    optional = spec.get("optional", {})
    allowed_keys = set(required) | set(optional)

    for key in payload:
        if key not in allowed_keys:
            raise ValueError(f"Unexpected payload key '{key}' for {command_type}")

    for key, expected_type in required.items():
        if key not in payload:
            raise ValueError(f"Missing required payload key '{key}' for {command_type}")
        if not isinstance(payload[key], expected_type):
            raise ValueError(
                f"Payload key '{key}' must be {expected_type.__name__} for {command_type}"
            )

    for key, expected_type in optional.items():
        if key in payload and not isinstance(payload[key], expected_type):
            raise ValueError(
                f"Payload key '{key}' must be {expected_type.__name__} for {command_type}"
            )

    if command_type == "event.mark":
        status = payload.get("status", "")
        if status not in EVENT_STATUSES:
            raise ValueError(
                f"Invalid event status '{status}'; "
                f"allowed: {', '.join(sorted(EVENT_STATUSES))}"
            )

    return payload


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
