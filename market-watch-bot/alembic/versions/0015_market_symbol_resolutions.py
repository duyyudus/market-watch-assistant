"""add market symbol resolutions

Revision ID: 0015_market_symbol_resolutions
Revises: 0014_active_url_dedup
Create Date: 2026-06-12
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0015_market_symbol_resolutions"
down_revision: str | None = "0014_active_url_dedup"
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

    op.create_table(
        "market_symbol_resolutions",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("watchlist_entity_id", sa.String(length=64), nullable=False),
        sa.Column("symbol", sa.String(length=64), nullable=True),
        sa.Column("asset_class", sa.String(length=64), nullable=True),
        sa.Column("region", sa.String(length=64), nullable=True),
        sa.Column("provider", sa.String(length=64), nullable=True),
        sa.Column("provider_symbol", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()).with_variant(sa.JSON(), "sqlite"),
            nullable=False,
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["watchlist_entity_id"],
            ["watchlist_entities.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "watchlist_entity_id",
            name="uq_market_symbol_resolution_watchlist",
        ),
    )
    op.create_index(
        "ix_market_symbol_resolutions_watchlist_entity_id",
        "market_symbol_resolutions",
        ["watchlist_entity_id"],
    )
    op.create_index(
        "ix_market_symbol_resolutions_provider_symbol",
        "market_symbol_resolutions",
        ["provider", "provider_symbol"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_market_symbol_resolutions_provider_symbol",
        table_name="market_symbol_resolutions",
    )
    op.drop_index(
        "ix_market_symbol_resolutions_watchlist_entity_id",
        table_name="market_symbol_resolutions",
    )
    op.drop_table("market_symbol_resolutions")
    with op.batch_alter_table("watchlist_entities") as batch_op:
        batch_op.alter_column("asset_class", existing_type=sa.String(length=64), nullable=True)
        batch_op.alter_column("region", existing_type=sa.String(length=64), nullable=True)
