from datetime import UTC, datetime

from bot_worker.retention import RetentionPolicy, retention_cutoffs


def test_retention_cutoffs_use_documented_defaults() -> None:
    now = datetime(2026, 5, 25, tzinfo=UTC)

    cutoffs = retention_cutoffs(now, RetentionPolicy())

    assert cutoffs["source_fetch_logs"].isoformat() == "2026-05-11T00:00:00+00:00"
    assert cutoffs["raw_news_items"].isoformat() == "2026-03-26T00:00:00+00:00"
    assert cutoffs["normalized_news_items"].isoformat() == "2025-11-26T00:00:00+00:00"
    assert cutoffs["event_clusters"].year == 2023
    assert cutoffs["alert_decisions"].year == 2025
