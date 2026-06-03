"""add event cluster item decision metadata

Revision ID: 0013_event_item_decision_meta
Revises: 0012_full_text_extraction_state
Create Date: 2026-06-03
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0013_event_item_decision_meta"
down_revision: str | None = "0012_full_text_extraction_state"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if not _has_column("event_cluster_items", "decision_metadata"):
        op.add_column(
            "event_cluster_items",
            sa.Column("decision_metadata", postgresql.JSONB()),
        )


def downgrade() -> None:
    if _has_column("event_cluster_items", "decision_metadata"):
        op.drop_column("event_cluster_items", "decision_metadata")


def _has_column(table_name: str, column_name: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return any(column["name"] == column_name for column in inspector.get_columns(table_name))
