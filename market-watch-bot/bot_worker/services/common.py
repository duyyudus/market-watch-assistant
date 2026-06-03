from __future__ import annotations

from datetime import datetime

from bot_worker.normalize import (
    normalize_datetime,
)


def _json_safe(value: object) -> object:
    if value is None or isinstance(value, int | float | bool):
        return value
    if isinstance(value, str):
        return value.replace("\x00", "")
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {_json_safe(str(key)): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_json_safe(item) for item in value]
    return str(value).replace("\x00", "")


def _published_to_string(value: object | None) -> str | None:
    published = normalize_datetime(value)
    return published.isoformat() if published else None


def _result_rowcount(result: object) -> int:
    return int(getattr(result, "rowcount", 0) or 0)
