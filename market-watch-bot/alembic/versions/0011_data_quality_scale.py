"""add data quality and scale controls

Revision ID: 0011_data_quality_scale
Revises: 0010_alert_delivery_controls
Create Date: 2026-06-01
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0011_data_quality_scale"
down_revision: str | None = "0010_alert_delivery_controls"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("news_sources", sa.Column("etag", sa.Text()))
    op.add_column("news_sources", sa.Column("last_modified", sa.Text()))
    op.add_column("news_sources", sa.Column("auto_quality_score", sa.Integer()))
    op.add_column("news_sources", sa.Column("quality_metrics", postgresql.JSONB()))
    op.add_column("news_sources", sa.Column("quality_calculated_at", sa.DateTime(timezone=True)))
    op.add_column("event_clusters", sa.Column("archive_summary", postgresql.JSONB()))
    op.add_column("event_clusters", sa.Column("compacted_at", sa.DateTime(timezone=True)))
    op.execute(
        sa.text(
            """
            UPDATE normalized_news_items
            SET processing_status = 'deduped'
            WHERE id IN (
                SELECT id
                FROM (
                    SELECT
                        id,
                        row_number() OVER (
                            PARTITION BY canonical_url_hash, title_hash
                            ORDER BY created_at ASC, id ASC
                        ) AS row_number
                    FROM normalized_news_items
                    WHERE processing_status = 'normalized'
                ) ranked
                WHERE ranked.row_number > 1
            )
            """
        )
    )
    op.create_index(
        "ix_normalized_news_items_active_dedup",
        "normalized_news_items",
        ["canonical_url_hash", "title_hash"],
        unique=True,
        postgresql_where=sa.text("processing_status = 'normalized'"),
        sqlite_where=sa.text("processing_status = 'normalized'"),
    )

    # Recreate FK constraints with explicit ondelete policy for Postgres deployments.
    dialect = op.get_context().dialect.name
    if dialect == "postgresql":
        _replace_fk(
            "source_fetch_logs",
            "source_fetch_logs_source_id_fkey",
            ["source_id"],
            "news_sources",
            ["id"],
            ondelete="CASCADE",
        )
        _replace_fk(
            "raw_news_items",
            "raw_news_items_source_id_fkey",
            ["source_id"],
            "news_sources",
            ["id"],
            ondelete="CASCADE",
        )
        _replace_fk(
            "normalized_news_items",
            "normalized_news_items_source_id_fkey",
            ["source_id"],
            "news_sources",
            ["id"],
            ondelete="CASCADE",
        )


def downgrade() -> None:
    op.drop_index("ix_normalized_news_items_active_dedup", table_name="normalized_news_items")
    op.drop_column("event_clusters", "compacted_at")
    op.drop_column("event_clusters", "archive_summary")
    op.drop_column("news_sources", "quality_calculated_at")
    op.drop_column("news_sources", "quality_metrics")
    op.drop_column("news_sources", "auto_quality_score")
    op.drop_column("news_sources", "last_modified")
    op.drop_column("news_sources", "etag")


def _replace_fk(
    table_name: str,
    constraint_name: str,
    local_cols: list[str],
    referent_table: str,
    remote_cols: list[str],
    *,
    ondelete: str,
) -> None:
    op.drop_constraint(constraint_name, table_name, type_="foreignkey")
    op.create_foreign_key(
        constraint_name,
        table_name,
        referent_table,
        local_cols,
        remote_cols,
        ondelete=ondelete,
    )
