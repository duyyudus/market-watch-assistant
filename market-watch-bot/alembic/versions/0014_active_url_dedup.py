"""add active normalized news canonical url dedup

Revision ID: 0014_active_url_dedup
Revises: 0013_event_item_decision_meta
Create Date: 2026-06-08
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0014_active_url_dedup"
down_revision: str | None = "0013_event_item_decision_meta"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


ACTIVE_URL_DEDUP_PREDICATE = (
    "processing_status = 'normalized' "
    "AND canonical_url_hash IS NOT NULL "
    "AND NOT (source_type = 'google-rss' AND snippet IS NOT NULL)"
)


def upgrade() -> None:
    op.execute(
        sa.text(
            f"""
            UPDATE normalized_news_items
            SET processing_status = 'deduped'
            WHERE id IN (
                SELECT id
                FROM (
                    SELECT
                        id,
                        row_number() OVER (
                            PARTITION BY canonical_url_hash
                            ORDER BY created_at ASC, id ASC
                        ) AS row_number
                    FROM normalized_news_items
                    WHERE {ACTIVE_URL_DEDUP_PREDICATE}
                ) ranked
                WHERE ranked.row_number > 1
            )
            """
        )
    )
    op.create_index(
        "ix_normalized_news_items_active_url_dedup",
        "normalized_news_items",
        ["canonical_url_hash"],
        unique=True,
        postgresql_where=sa.text(ACTIVE_URL_DEDUP_PREDICATE),
        sqlite_where=sa.text(ACTIVE_URL_DEDUP_PREDICATE),
    )


def downgrade() -> None:
    op.drop_index("ix_normalized_news_items_active_url_dedup", table_name="normalized_news_items")
