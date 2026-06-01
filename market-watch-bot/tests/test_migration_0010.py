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
