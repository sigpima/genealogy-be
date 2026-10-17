"""gd3 branches

Revision ID: a3f1c9d2b7e4
Revises: 8392e7de205b
Create Date: 2026-10-18 09:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a3f1c9d2b7e4"
down_revision: Union[str, Sequence[str], None] = "8392e7de205b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "branches",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tree_id", sa.Integer(), sa.ForeignKey("trees.id"), nullable=False),
        sa.Column("name", sa.String(length=150), nullable=False),
        sa.Column("color", sa.String(length=7), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "root_member_id",
            sa.Integer(),
            sa.ForeignKey("members.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_branches_tree_id", "branches", ["tree_id"])


def downgrade() -> None:
    op.drop_index("ix_branches_tree_id", table_name="branches")
    op.drop_table("branches")
