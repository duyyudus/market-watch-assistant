"""enforce non-null watchlist region/asset_class

Revision ID: 0016_watchlist_region_not_null
Revises: 0015_market_symbol_resolutions
Create Date: 2026-06-13

The backfill and NOT NULL constraint were added to 0015 after that revision had
already been applied to some databases, so alembic never ran them there. This
forward migration reapplies them idempotently.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0016_watchlist_region_not_null"
down_revision: str | None = "0015_market_symbol_resolutions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("UPDATE watchlist_entities SET region = 'other' WHERE region IS NULL")
    op.execute(
        "UPDATE watchlist_entities SET asset_class = 'global_macro' WHERE asset_class IS NULL"
    )
    with op.batch_alter_table("watchlist_entities") as batch_op:
        batch_op.alter_column("region", existing_type=sa.String(length=64), nullable=False)
        batch_op.alter_column("asset_class", existing_type=sa.String(length=64), nullable=False)


def downgrade() -> None:
    with op.batch_alter_table("watchlist_entities") as batch_op:
        batch_op.alter_column("asset_class", existing_type=sa.String(length=64), nullable=True)
        batch_op.alter_column("region", existing_type=sa.String(length=64), nullable=True)
