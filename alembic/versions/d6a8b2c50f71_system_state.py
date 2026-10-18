"""superadmin console: system_state (small key/value facts about the running system, e.g. the reminder worker's last run)

Revision ID: d6a8b2c50f71
Revises: c5f7a1b49e60
Create Date: 2026-10-18
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d6a8b2c50f71"
down_revision: Union[str, Sequence[str], None] = "c5f7a1b49e60"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "system_state",
        sa.Column("key", sa.String(60), primary_key=True),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("system_state")
