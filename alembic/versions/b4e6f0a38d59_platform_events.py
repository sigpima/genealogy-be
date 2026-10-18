"""superadmin console: platform_events

Revision ID: b4e6f0a38d59
Revises: a3d5e9f27c48
Create Date: 2026-10-18
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b4e6f0a38d59"
down_revision: Union[str, Sequence[str], None] = "a3d5e9f27c48"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "platform_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("actor_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("actor_name", sa.String(255), nullable=False),
        sa.Column("action", sa.String(40), nullable=False),
        sa.Column("tree_id", sa.Integer(), nullable=True),  # no FK on purpose: the entries of a deleted family survive
        sa.Column("tree_name", sa.String(255), nullable=True),
        sa.Column("details", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_platform_events_created_at", "platform_events", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_platform_events_created_at", table_name="platform_events")
    op.drop_table("platform_events")
