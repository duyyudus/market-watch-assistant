from pathlib import Path


def test_alert_delivery_controls_migration_declares_tables_columns_and_indexes() -> None:
    migration = Path("alembic/versions/0010_alert_delivery_controls.py").read_text(
        encoding="utf-8"
    )

    expected_fragments = [
        "alert_channels",
        "alert_suppression_rules",
        "acknowledged_at",
        "attempt_count",
        "next_attempt_at",
        "permanently_failed_at",
        "ix_alert_channels_enabled_default",
        "ix_alert_suppression_rules_enabled_type",
        "ix_alert_decisions_acknowledged_at",
        "ix_alert_deliveries_retryable",
    ]
    for fragment in expected_fragments:
        assert fragment in migration


def test_data_quality_scale_migration_declares_columns_indexes_and_fk_policy() -> None:
    migration = Path("alembic/versions/0011_data_quality_scale.py").read_text(
        encoding="utf-8"
    )

    expected_fragments = [
        "etag",
        "last_modified",
        "auto_quality_score",
        "quality_metrics",
        "quality_calculated_at",
        "archive_summary",
        "compacted_at",
        "ix_normalized_news_items_active_dedup",
        "postgresql_where",
        "processing_status = 'normalized'",
        "ondelete=",
    ]
    for fragment in expected_fragments:
        assert fragment in migration


def test_full_text_extraction_state_migration_declares_item_state_columns() -> None:
    migration = Path("alembic/versions/0012_full_text_extraction_state.py").read_text(
        encoding="utf-8"
    )

    expected_fragments = [
        "full_text_extraction_status",
        "full_text_attempt_count",
        "full_text_last_attempted_at",
        "full_text_last_http_status",
        "full_text_last_error",
        "full_text_next_retry_at",
        "full_text_available = true",
        "full_text_available = false",
        "ix_normalized_news_items_full_text_retry",
    ]
    for fragment in expected_fragments:
        assert fragment in migration


def test_active_url_dedup_migration_declares_backfill_and_index() -> None:
    migration_paths = sorted(Path("alembic/versions").glob("*active_url_dedup*.py"))
    assert len(migration_paths) == 1
    migration = migration_paths[0].read_text(encoding="utf-8")

    expected_fragments = [
        "down_revision: str | None = \"0013_event_item_decision_meta\"",
        "row_number() OVER",
        "PARTITION BY canonical_url_hash",
        "processing_status = 'normalized'",
        "ix_normalized_news_items_active_url_dedup",
        "[\"canonical_url_hash\"]",
        "canonical_url_hash IS NOT NULL",
    ]
    for fragment in expected_fragments:
        assert fragment in migration
