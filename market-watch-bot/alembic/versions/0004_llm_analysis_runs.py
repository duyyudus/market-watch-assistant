"""add llm analysis runs

Revision ID: 0004_llm_analysis_runs
Revises: 0003_event_embed_idx
Create Date: 2026-05-27
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0004_llm_analysis_runs"
down_revision: str | None = "0003_event_embed_idx"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "llm_analysis_runs",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("target_type", sa.String(32), nullable=False),
        sa.Column("target_id", sa.String(64), nullable=False),
        sa.Column("provider", sa.String(64), nullable=False),
        sa.Column("model", sa.String(255), nullable=False),
        sa.Column("prompt_version", sa.String(64), nullable=False),
        sa.Column("prompt_hash", sa.String(64), nullable=False),
        sa.Column("input_snapshot", postgresql.JSONB, nullable=False),
        sa.Column("result", postgresql.JSONB),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("error_message", sa.Text),
        sa.Column("usage", postgresql.JSONB),
        sa.Column("created_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint(
            "target_type",
            "target_id",
            "provider",
            "model",
            "prompt_version",
            name="uq_llm_analysis_runs_target_model_prompt",
        ),
    )
    op.create_index(
        "ix_llm_analysis_runs_target",
        "llm_analysis_runs",
        ["target_type", "target_id"],
    )
    op.create_index(
        "ix_llm_analysis_runs_status_created",
        "llm_analysis_runs",
        ["status", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_llm_analysis_runs_status_created", table_name="llm_analysis_runs")
    op.drop_index("ix_llm_analysis_runs_target", table_name="llm_analysis_runs")
    op.drop_table("llm_analysis_runs")
