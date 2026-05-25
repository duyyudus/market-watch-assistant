from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo


def digest_window_for_date(value: str, timezone: ZoneInfo) -> tuple[datetime, datetime]:
    local_date = date.fromisoformat(value)
    start_local = datetime.combine(local_date, time.min, tzinfo=timezone)
    end_local = datetime.combine(local_date + timedelta(days=1), time.min, tzinfo=timezone)
    return start_local.astimezone(UTC), end_local.astimezone(UTC)
