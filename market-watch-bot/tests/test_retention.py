from datetime import UTC, datetime

from sqlalchemy.sql.dml import Delete
from sqlalchemy.sql.selectable import Select

from bot_worker.db.models import (
    AppSetting,
    NewsEntity,
    NewsSource,
    NormalizedNewsItem,
    RawNewsItem,
    WatchlistEntity,
)
from bot_worker.retention import RetentionPolicy, retention_cutoffs
from bot_worker.services.retention import (
    BASELINE_RESET_TARGET_TABLES,
    baseline_reset_preview,
    run_baseline_reset,
)


def test_retention_cutoffs_use_documented_defaults() -> None:
    now = datetime(2026, 5, 25, tzinfo=UTC)

    cutoffs = retention_cutoffs(now, RetentionPolicy())

    assert cutoffs["source_fetch_logs"].isoformat() == "2026-05-11T00:00:00+00:00"
    assert cutoffs["raw_news_items"].isoformat() == "2026-03-26T00:00:00+00:00"
    assert cutoffs["normalized_news_items"].isoformat() == "2025-11-26T00:00:00+00:00"
    assert cutoffs["event_clusters"].year == 2023
    assert cutoffs["alert_decisions"].year == 2025


class CountSession:
    def __init__(self, counts: dict[str, int]) -> None:
        self.counts = counts
        self.counted_tables: list[str] = []

    async def scalar(self, stmt: Select) -> int:
        table_name = stmt.get_final_froms()[0].name
        self.counted_tables.append(table_name)
        return self.counts[table_name]


class DeleteResult:
    def __init__(self, rowcount: int) -> None:
        self.rowcount = rowcount


class DeleteSession:
    def __init__(self, counts: dict[str, int]) -> None:
        self.counts = counts
        self.deleted_tables: list[str] = []

    async def execute(self, stmt: Delete) -> DeleteResult:
        table_name = stmt.table.name
        self.deleted_tables.append(table_name)
        return DeleteResult(self.counts[table_name])


def test_baseline_reset_preserved_tables_are_not_targeted() -> None:
    preserved_tables = {
        NewsSource.__tablename__,
        RawNewsItem.__tablename__,
        NormalizedNewsItem.__tablename__,
        NewsEntity.__tablename__,
        WatchlistEntity.__tablename__,
        AppSetting.__tablename__,
    }

    cleanup_tables = set(BASELINE_RESET_TARGET_TABLES)

    assert cleanup_tables.isdisjoint(preserved_tables)


async def test_baseline_reset_preview_counts_cleanup_tables() -> None:
    counts = {
        table_name: index
        for index, table_name in enumerate(BASELINE_RESET_TARGET_TABLES, start=1)
    }
    session = CountSession(counts)

    preview = await baseline_reset_preview(session)

    assert preview == counts
    assert session.counted_tables == list(BASELINE_RESET_TARGET_TABLES)


async def test_run_baseline_reset_deletes_tables_in_fk_safe_order() -> None:
    counts = {
        table_name: index
        for index, table_name in enumerate(BASELINE_RESET_TARGET_TABLES, start=1)
    }
    session = DeleteSession(counts)

    deleted = await run_baseline_reset(session)

    assert deleted == counts
    assert session.deleted_tables == [
        "alert_deliveries",
        "alert_decisions",
        "event_score_history",
        "event_cluster_embeddings",
        "event_cluster_items",
        "missed_catalyst_reviews",
        "event_clusters",
        "news_item_embeddings",
        "llm_analysis_runs",
        "market_moves",
        "source_fetch_logs",
        "job_runs",
        "retention_jobs",
    ]
