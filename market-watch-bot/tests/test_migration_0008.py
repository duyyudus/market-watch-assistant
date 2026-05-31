from pathlib import Path


def test_performance_index_migration_declares_track_1_indexes() -> None:
    migration = Path("alembic/versions/0008_performance_indexes.py").read_text(
        encoding="utf-8"
    )

    expected_fragments = [
        "bot_commands",
        "status",
        "created_at",
        "normalized_news_items",
        "processing_status",
        "alert_decisions",
        "sent_at",
        "agent_investigations",
        "event_clusters",
        "last_updated_at",
        "job_runs",
        "started_at",
        "postgresql_ops={\"started_at\": \"DESC\"}",
    ]
    for fragment in expected_fragments:
        assert fragment in migration
