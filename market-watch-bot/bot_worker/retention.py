from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass(frozen=True)
class RetentionPolicy:
    fetch_logs_days: int = 14
    raw_news_items_days: int = 60
    normalized_news_items_days: int = 180
    event_clusters_days: int = 1095
    alert_decisions_days: int = 365


def retention_cutoffs(now: datetime, policy: RetentionPolicy) -> dict[str, datetime]:
    return {
        "source_fetch_logs": now - timedelta(days=policy.fetch_logs_days),
        "raw_news_items": now - timedelta(days=policy.raw_news_items_days),
        "normalized_news_items": now - timedelta(days=policy.normalized_news_items_days),
        "event_clusters": now - timedelta(days=policy.event_clusters_days),
        "alert_decisions": now - timedelta(days=policy.alert_decisions_days),
    }
