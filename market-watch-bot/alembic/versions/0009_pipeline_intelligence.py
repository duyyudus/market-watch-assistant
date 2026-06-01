"""add pipeline intelligence state

Revision ID: 0009_pipeline_intelligence
Revises: 0008_performance_indexes
Create Date: 2026-05-31
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0009_pipeline_intelligence"
down_revision: str | None = "0008_performance_indexes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("news_sources", sa.Column("last_fetched_at", sa.DateTime(timezone=True)))
    op.add_column(
        "news_sources",
        sa.Column("consecutive_failure_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column("news_sources", sa.Column("burst_until_at", sa.DateTime(timezone=True)))
    op.add_column("news_sources", sa.Column("disabled_until_at", sa.DateTime(timezone=True)))
    op.add_column("normalized_news_items", sa.Column("raw_content", sa.Text()))
    op.add_column(
        "event_clusters",
        sa.Column("high_quality_source_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_table(
        "provider_cooldowns",
        sa.Column("provider", sa.String(64), primary_key=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="cooling_down"),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("http_status", sa.Integer()),
        sa.Column("cooldown_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_observed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
    )
    op.create_table(
        "digests",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("digest_type", sa.String(32), nullable=False, server_default="daily"),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="built"),
        sa.Column("event_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("channel", sa.String(32)),
        sa.Column("recipient", sa.String(255)),
        sa.Column("provider_response", postgresql.JSONB()),
        sa.Column("error_message", sa.Text()),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True)),
    )


def downgrade() -> None:
    op.drop_table("digests")
    op.drop_table("provider_cooldowns")
    op.drop_column("event_clusters", "high_quality_source_count")
    op.drop_column("normalized_news_items", "raw_content")
    op.drop_column("news_sources", "disabled_until_at")
    op.drop_column("news_sources", "burst_until_at")
    op.drop_column("news_sources", "consecutive_failure_count")
    op.drop_column("news_sources", "last_fetched_at")
