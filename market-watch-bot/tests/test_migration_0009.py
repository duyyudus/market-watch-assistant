from pathlib import Path


def test_track_2_migration_declares_pipeline_intelligence_tables_and_columns() -> None:
    migration = Path("alembic/versions/0009_pipeline_intelligence.py").read_text(
        encoding="utf-8"
    )

    expected_fragments = [
        "provider_cooldowns",
        "digests",
        "last_fetched_at",
        "consecutive_failure_count",
        "burst_until_at",
        "disabled_until_at",
        "raw_content",
        "high_quality_source_count",
    ]
    for fragment in expected_fragments:
        assert fragment in migration
