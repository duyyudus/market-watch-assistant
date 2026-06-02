"""add full text extraction state

Revision ID: 0012_full_text_extraction_state
Revises: 0011_data_quality_scale
Create Date: 2026-06-02
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0012_full_text_extraction_state"
down_revision: str | None = "0011_data_quality_scale"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "normalized_news_items",
        sa.Column(
            "full_text_extraction_status",
            sa.String(32),
            nullable=False,
            server_default="pending",
        ),
    )
    op.add_column(
        "normalized_news_items",
        sa.Column("full_text_attempt_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "normalized_news_items",
        sa.Column("full_text_last_attempted_at", sa.DateTime(timezone=True)),
    )
    op.add_column("normalized_news_items", sa.Column("full_text_last_http_status", sa.Integer()))
    op.add_column("normalized_news_items", sa.Column("full_text_last_error", sa.Text()))
    op.add_column(
        "normalized_news_items",
        sa.Column("full_text_next_retry_at", sa.DateTime(timezone=True)),
    )
    op.execute(
        sa.text(
            """
            UPDATE normalized_news_items
            SET full_text_extraction_status = 'extracted'
            WHERE full_text_available = true
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE normalized_news_items
            SET full_text_extraction_status = 'pending'
            WHERE full_text_available = false
            """
        )
    )
    op.create_index(
        "ix_normalized_news_items_full_text_retry",
        "normalized_news_items",
        ["full_text_available", "full_text_extraction_status", "full_text_next_retry_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_normalized_news_items_full_text_retry",
        table_name="normalized_news_items",
    )
    op.drop_column("normalized_news_items", "full_text_next_retry_at")
    op.drop_column("normalized_news_items", "full_text_last_error")
    op.drop_column("normalized_news_items", "full_text_last_http_status")
    op.drop_column("normalized_news_items", "full_text_last_attempted_at")
    op.drop_column("normalized_news_items", "full_text_attempt_count")
    op.drop_column("normalized_news_items", "full_text_extraction_status")
