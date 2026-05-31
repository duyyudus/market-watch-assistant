"""add track 1 performance indexes

Revision ID: 0008_performance_indexes
Revises: 0007_bot_commands
Create Date: 2026-05-31
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0008_performance_indexes"
down_revision: str | None = "0007_bot_commands"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_bot_commands_status_created_at",
        "bot_commands",
        ["status", "created_at"],
    )
    op.create_index(
        "ix_normalized_news_items_processing_status",
        "normalized_news_items",
        ["processing_status"],
    )
    op.create_index(
        "ix_alert_decisions_sent_at",
        "alert_decisions",
        ["sent_at"],
    )
    op.create_index(
        "ix_agent_investigations_status_created_at",
        "agent_investigations",
        ["status", "created_at"],
    )
    op.create_index(
        "ix_event_clusters_last_updated_at",
        "event_clusters",
        ["last_updated_at"],
    )
    op.create_index(
        "ix_job_runs_started_at_desc",
        "job_runs",
        [sa.text("started_at DESC")],
        postgresql_ops={"started_at": "DESC"},
    )


def downgrade() -> None:
    op.drop_index("ix_job_runs_started_at_desc", table_name="job_runs")
    op.drop_index("ix_event_clusters_last_updated_at", table_name="event_clusters")
    op.drop_index("ix_agent_investigations_status_created_at", table_name="agent_investigations")
    op.drop_index("ix_alert_decisions_sent_at", table_name="alert_decisions")
    op.drop_index(
        "ix_normalized_news_items_processing_status",
        table_name="normalized_news_items",
    )
    op.drop_index("ix_bot_commands_status_created_at", table_name="bot_commands")
