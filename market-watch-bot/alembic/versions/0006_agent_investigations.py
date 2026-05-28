"""add agent investigation records

Revision ID: 0006_agent_investigations
Revises: 0005_alert_deliveries
Create Date: 2026-05-28
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0006_agent_investigations"
down_revision: str | None = "0005_alert_deliveries"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agent_investigations",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("target_type", sa.String(32), nullable=False),
        sa.Column("target_id", sa.String(64), nullable=False),
        sa.Column("trigger_reason", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("input_snapshot", postgresql.JSONB, nullable=False),
        sa.Column("evidence", postgresql.JSONB, nullable=False),
        sa.Column("provider", sa.String(64)),
        sa.Column("model", sa.String(255)),
        sa.Column("prompt_version", sa.String(64)),
        sa.Column("prompt_hash", sa.String(64)),
        sa.Column("result", postgresql.JSONB),
        sa.Column("usage", postgresql.JSONB),
        sa.Column("error_message", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
    )
    op.create_index(
        "ix_agent_investigations_target_created",
        "agent_investigations",
        ["target_type", "target_id", "created_at"],
    )
    op.create_index(
        "ix_agent_investigations_status_created",
        "agent_investigations",
        ["status", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_agent_investigations_status_created", table_name="agent_investigations")
    op.drop_index("ix_agent_investigations_target_created", table_name="agent_investigations")
    op.drop_table("agent_investigations")
