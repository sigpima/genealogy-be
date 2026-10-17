"""gd5 calendar: events, notifications, reminder settings, calendar token

Revision ID: c5e8a1f03d92
Revises: b7d4e2a91c05
Create Date: 2026-10-18 20:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c5e8a1f03d92"
down_revision: Union[str, Sequence[str], None] = "b7d4e2a91c05"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tree_id", sa.Integer(), sa.ForeignKey("trees.id"), nullable=False),
        sa.Column("title", sa.String(length=150), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("kind", sa.String(length=12), nullable=False),
        sa.Column("calendar", sa.String(length=5), nullable=False),
        sa.Column("year", sa.Integer(), nullable=True),
        sa.Column("month", sa.SmallInteger(), nullable=False),
        sa.Column("day", sa.SmallInteger(), nullable=False),
        sa.Column("repeats_yearly", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("time_text", sa.String(length=5), nullable=True),
        sa.Column("location", sa.String(length=255), nullable=True),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_events_tree_id", "events", ["tree_id"])
    op.create_table(
        "notifications",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("tree_id", sa.Integer(), sa.ForeignKey("trees.id"), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("link", sa.String(length=255), nullable=True),
        sa.Column("dedupe_key", sa.String(length=120), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("user_id", "dedupe_key", name="uq_notifications_user_dedupe"),
    )
    op.create_index("ix_notifications_user_id", "notifications", ["user_id"])
    op.add_column("users", sa.Column("reminder_days", sa.String(length=40), nullable=False, server_default="7,1"))
    op.add_column("users", sa.Column("reminder_email", sa.Boolean(), nullable=False, server_default=sa.true()))
    op.add_column("trees", sa.Column("calendar_token", sa.String(length=64), nullable=True))
    op.create_index("ix_trees_calendar_token", "trees", ["calendar_token"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_trees_calendar_token", table_name="trees")
    op.drop_column("trees", "calendar_token")
    op.drop_column("users", "reminder_email")
    op.drop_column("users", "reminder_days")
    op.drop_index("ix_notifications_user_id", table_name="notifications")
    op.drop_table("notifications")
    op.drop_index("ix_events_tree_id", table_name="events")
    op.drop_table("events")
