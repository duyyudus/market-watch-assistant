"""add is_primary flag to news entities

Revision ID: 0017_news_entity_is_primary
Revises: 0016_watchlist_region_not_null
Create Date: 2026-06-17
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0017_news_entity_is_primary"
down_revision: str | None = "0016_watchlist_region_not_null"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "news_entities",
        sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("news_entities", "is_primary")
