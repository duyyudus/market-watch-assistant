from __future__ import annotations

from typing import Any

ALLOWED_COMMAND_TYPES = {
    "source.fetch",
    "alert.dispatch",
    "alert.test_channel",
    "digest.send",
    "event.rescore",
    "event.mark",
    "event.recluster",
    "event.merge",
    "event.split",
    "event.compact_archived",
    "source.quality.refresh",
    "investigation.run_event",
    "retention.preview",
    "retention.run",
    "market.fetch",
    "catalyst.review",
}

EVENT_STATUSES = {"reported", "confirmed", "official", "stale", "false_signal", "merged"}

PAYLOAD_VALIDATORS: dict[str, dict[str, dict[str, type]]] = {
    "source.fetch": {"required": {"source_id": str}},
    "alert.dispatch": {"optional": {"channel": str, "limit": int, "dry_run": bool}},
    "alert.test_channel": {"required": {"channel_id": str}, "optional": {"message": str}},
    "digest.send": {"optional": {"hours": int, "limit": int, "dry_run": bool}},
    "event.rescore": {"required": {"event_id": str}},
    "event.mark": {"required": {"event_id": str, "status": str}},
    "event.recluster": {
        "optional": {"since": str, "limit": int, "apply": bool, "llm": bool, "embed": bool},
    },
    "event.merge": {"required": {"source_event_id": str, "target_event_id": str}},
    "event.split": {"required": {"event_id": str, "news_item_ids": list}},
    "event.compact_archived": {
        "optional": {"older_than": str, "limit": int, "apply": bool},
    },
    "source.quality.refresh": {},
    "investigation.run_event": {"required": {"event_id": str}},
    "retention.preview": {},
    "retention.run": {},
    "market.fetch": {},
    "catalyst.review": {},
}


def validate_command_payload(command_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    if command_type not in ALLOWED_COMMAND_TYPES:
        raise ValueError(f"Unsupported command type: {command_type}")

    spec = PAYLOAD_VALIDATORS[command_type]
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
