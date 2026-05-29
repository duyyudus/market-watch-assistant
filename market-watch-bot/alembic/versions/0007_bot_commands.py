"""add bot command queue

Revision ID: 0007_bot_commands
Revises: 0006_agent_investigations
Create Date: 2026-05-29
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0007_bot_commands"
down_revision: str | None = "0006_agent_investigations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "bot_commands",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("command_type", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("payload", postgresql.JSONB, nullable=False),
        sa.Column("result", postgresql.JSONB),
        sa.Column("error_message", sa.Text),
        sa.Column("requested_by", sa.String(255)),
        sa.Column("created_at", sa.DateTime(timezone=True)),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_bot_commands_status_created", "bot_commands", ["status", "created_at"])
    op.create_index("ix_bot_commands_type_created", "bot_commands", ["command_type", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_bot_commands_type_created", table_name="bot_commands")
    op.drop_index("ix_bot_commands_status_created", table_name="bot_commands")
    op.drop_table("bot_commands")
