"""invitation links: one link per person of the tree

Revision ID: f8c0d4e72b93
Revises: e7b9c3d61a82
Create Date: 2026-10-19 11:00:00
"""

import sqlalchemy as sa
from alembic import op

revision = "f8c0d4e72b93"
down_revision = "e7b9c3d61a82"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "member_invites",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tree_id", sa.Integer(), sa.ForeignKey("trees.id", ondelete="CASCADE"), nullable=False),
        sa.Column("member_id", sa.Integer(), sa.ForeignKey("members.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("used_at", sa.DateTime(), nullable=True),
        sa.Column("used_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_member_invites_tree_id", "member_invites", ["tree_id"])
    op.create_index("ix_member_invites_member_id", "member_invites", ["member_id"])
    op.create_index("ix_member_invites_token_hash", "member_invites", ["token_hash"], unique=True)
    op.create_index(
        "uq_member_invites_open_per_member",
        "member_invites",
        ["member_id"],
        unique=True,
        postgresql_where=sa.text("used_at IS NULL AND revoked_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_table("member_invites")
