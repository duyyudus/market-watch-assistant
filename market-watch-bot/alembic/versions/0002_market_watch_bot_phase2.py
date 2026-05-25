"""market watch bot phase 2 embeddings and market data

Revision ID: 0002_market_watch_bot_phase2
Revises: 0001_market_watch_bot_mvp
Create Date: 2026-05-25
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0002_market_watch_bot_phase2"
down_revision: str | None = "0001_market_watch_bot_mvp"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


class Vector(sa.types.UserDefinedType):
    cache_ok = True

    def __init__(self, dimensions: int) -> None:
        self.dimensions = dimensions

    def get_col_spec(self, **_kw: object) -> str:
        return f"vector({self.dimensions})"


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "news_item_embeddings",
        sa.Column(
            "news_item_id",
            sa.String(64),
            sa.ForeignKey("normalized_news_items.id"),
            primary_key=True,
        ),
        sa.Column("provider", sa.String(64), nullable=False),
        sa.Column("embedding_model", sa.String(255), nullable=False),
        sa.Column("embedding_version", sa.String(64), nullable=False),
        sa.Column("dimensions", sa.Integer, nullable=False),
        sa.Column("embedding_text_hash", sa.String(64), nullable=False),
        sa.Column("vector", Vector(1536), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True)),
    )
    op.create_table(
        "event_cluster_embeddings",
        sa.Column(
            "event_cluster_id",
            sa.String(64),
            sa.ForeignKey("event_clusters.id"),
            primary_key=True,
        ),
        sa.Column("provider", sa.String(64), nullable=False),
        sa.Column("embedding_model", sa.String(255), nullable=False),
        sa.Column("embedding_version", sa.String(64), nullable=False),
        sa.Column("dimensions", sa.Integer, nullable=False),
        sa.Column("embedding_text_hash", sa.String(64), nullable=False),
        sa.Column("vector", Vector(1536), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
    )
    op.create_table(
        "market_moves",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("asset_symbol", sa.String(64), nullable=False),
        sa.Column("asset_class", sa.String(64), nullable=False),
        sa.Column("exchange", sa.String(64)),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window", sa.String(16), nullable=False),
        sa.Column("price_change_pct", sa.Float, nullable=False),
        sa.Column("volume_change_pct", sa.Float),
        sa.Column("value_traded_change_pct", sa.Float),
        sa.Column("z_score", sa.Float),
        sa.Column("created_at", sa.DateTime(timezone=True)),
    )
    op.create_table(
        "missed_catalyst_reviews",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("asset_symbol", sa.String(64), nullable=False),
        sa.Column("asset_class", sa.String(64), nullable=False),
        sa.Column("move_window", sa.String(16), nullable=False),
        sa.Column("price_change_pct", sa.Float, nullable=False),
        sa.Column("volume_change_pct", sa.Float),
        sa.Column("detected_event_cluster_id", sa.String(64), sa.ForeignKey("event_clusters.id")),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("agent_summary", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
    )


def downgrade() -> None:
    for table in [
        "missed_catalyst_reviews",
        "market_moves",
        "event_cluster_embeddings",
        "news_item_embeddings",
    ]:
        op.drop_table(table)
