"""gd4 change requests and audit log

Revision ID: b7d4e2a91c05
Revises: a3f1c9d2b7e4
Create Date: 2026-10-18 14:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b7d4e2a91c05"
down_revision: Union[str, Sequence[str], None] = "a3f1c9d2b7e4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "change_requests",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tree_id", sa.Integer(), sa.ForeignKey("trees.id"), nullable=False),
        sa.Column("member_id", sa.Integer(), sa.ForeignKey("members.id", ondelete="SET NULL"), nullable=True),
        sa.Column("member_name", sa.String(length=255), nullable=True),
        sa.Column("requester_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("requester_name", sa.String(length=255), nullable=False),
        sa.Column("kind", sa.String(length=10), nullable=False),
        sa.Column("status", sa.String(length=10), nullable=False, server_default="pending"),
        sa.Column("changes", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("base", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("reviewer_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("reviewer_name", sa.String(length=255), nullable=True),
        sa.Column("review_note", sa.Text(), nullable=True),
        sa.Column("result_member_id", sa.Integer(), sa.ForeignKey("members.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_change_requests_tree_id", "change_requests", ["tree_id"])
    op.create_index("ix_change_requests_requester_id", "change_requests", ["requester_id"])
    op.create_table(
        "audit_log",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tree_id", sa.Integer(), sa.ForeignKey("trees.id"), nullable=False),
        sa.Column("actor_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("actor_name", sa.String(length=255), nullable=False),
        sa.Column("action", sa.String(length=40), nullable=False),
        sa.Column("member_id", sa.Integer(), nullable=True),
        sa.Column("member_name", sa.String(length=255), nullable=True),
        sa.Column("changes", postgresql.JSONB(), nullable=True),
        sa.Column("details", postgresql.JSONB(), nullable=True),
        sa.Column("request_id", sa.Integer(), sa.ForeignKey("change_requests.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_audit_log_tree_id", "audit_log", ["tree_id"])
    op.create_index("ix_audit_log_member_id", "audit_log", ["member_id"])


def downgrade() -> None:
    op.drop_index("ix_audit_log_member_id", table_name="audit_log")
    op.drop_index("ix_audit_log_tree_id", table_name="audit_log")
    op.drop_table("audit_log")
    op.drop_index("ix_change_requests_requester_id", table_name="change_requests")
    op.drop_index("ix_change_requests_tree_id", table_name="change_requests")
    op.drop_table("change_requests")
