"""add alert delivery controls

Revision ID: 0010_alert_delivery_controls
Revises: 0009_pipeline_intelligence
Create Date: 2026-06-01
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0010_alert_delivery_controls"
down_revision: str | None = "0009_pipeline_intelligence"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "alert_channels",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("channel_type", sa.String(32), nullable=False),
        sa.Column("config", postgresql.JSONB(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
    )
    op.create_index(
        "ix_alert_channels_enabled_default",
        "alert_channels",
        ["enabled", "is_default", "channel_type"],
    )
    op.create_table(
        "alert_suppression_rules",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("rule_type", sa.String(32), nullable=False),
        sa.Column("config", postgresql.JSONB(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
    )
    op.create_index(
        "ix_alert_suppression_rules_enabled_type",
        "alert_suppression_rules",
        ["enabled", "rule_type"],
    )
    op.add_column("alert_decisions", sa.Column("acknowledged_at", sa.DateTime(timezone=True)))
    op.create_index(
        "ix_alert_decisions_acknowledged_at",
        "alert_decisions",
        ["acknowledged_at", "created_at"],
    )
    op.add_column(
        "alert_deliveries",
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column("alert_deliveries", sa.Column("next_attempt_at", sa.DateTime(timezone=True)))
    op.add_column(
        "alert_deliveries",
        sa.Column("permanently_failed_at", sa.DateTime(timezone=True)),
    )
    op.create_index(
        "ix_alert_deliveries_retryable",
        "alert_deliveries",
        ["status", "next_attempt_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_alert_deliveries_retryable", table_name="alert_deliveries")
    op.drop_column("alert_deliveries", "permanently_failed_at")
    op.drop_column("alert_deliveries", "next_attempt_at")
    op.drop_column("alert_deliveries", "attempt_count")
    op.drop_index("ix_alert_decisions_acknowledged_at", table_name="alert_decisions")
    op.drop_column("alert_decisions", "acknowledged_at")
    op.drop_index("ix_alert_suppression_rules_enabled_type", table_name="alert_suppression_rules")
    op.drop_table("alert_suppression_rules")
    op.drop_index("ix_alert_channels_enabled_default", table_name="alert_channels")
    op.drop_table("alert_channels")
