"""add event embedding vector search indexes

Revision ID: 0003_event_embed_idx
Revises: 0002_market_watch_bot_phase2
Create Date: 2026-05-26
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0003_event_embed_idx"
down_revision: str | None = "0002_market_watch_bot_phase2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_event_cluster_embeddings_vector_hnsw_cosine
        ON event_cluster_embeddings
        USING hnsw (vector vector_cosine_ops)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_event_cluster_embeddings_model_filter
        ON event_cluster_embeddings
        (provider, embedding_model, embedding_version, dimensions)
        """
    )


def downgrade() -> None:
    op.drop_index(
        "ix_event_cluster_embeddings_model_filter",
        table_name="event_cluster_embeddings",
    )
    op.execute("DROP INDEX IF EXISTS ix_event_cluster_embeddings_vector_hnsw_cosine")
