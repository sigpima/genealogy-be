"""superadmin console: trees.status (active | paused)

Revision ID: c5f7a1b49e60
Revises: b4e6f0a38d59
Create Date: 2026-10-18
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c5f7a1b49e60"
down_revision: Union[str, Sequence[str], None] = "b4e6f0a38d59"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("trees", sa.Column("status", sa.String(10), nullable=False, server_default="active"))


def downgrade() -> None:
    op.drop_column("trees", "status")
