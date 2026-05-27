"""add alert delivery records

Revision ID: 0005_alert_deliveries
Revises: 0004_llm_analysis_runs
Create Date: 2026-05-27
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0005_alert_deliveries"
down_revision: str | None = "0004_llm_analysis_runs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "alert_deliveries",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("alert_decision_id", sa.String(64), sa.ForeignKey("alert_decisions.id")),
        sa.Column("channel", sa.String(32), nullable=False),
        sa.Column("recipient", sa.String(255), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("message_text", sa.Text, nullable=False),
        sa.Column("provider_response", postgresql.JSONB),
        sa.Column("error_message", sa.Text),
        sa.Column("attempted_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True)),
    )
    op.create_index(
        "ix_alert_deliveries_alert_decision_created",
        "alert_deliveries",
        ["alert_decision_id", "created_at"],
    )
    op.create_index(
        "ix_alert_deliveries_status_created",
        "alert_deliveries",
        ["status", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_alert_deliveries_status_created", table_name="alert_deliveries")
    op.drop_index("ix_alert_deliveries_alert_decision_created", table_name="alert_deliveries")
    op.drop_table("alert_deliveries")
