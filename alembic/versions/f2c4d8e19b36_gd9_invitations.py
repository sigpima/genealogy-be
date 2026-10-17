"""gd9 invitation cards and RSVPs

Revision ID: f2c4d8e19b36
Revises: e1b3c7d85a29
Create Date: 2026-10-19 16:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f2c4d8e19b36"
down_revision: Union[str, Sequence[str], None] = "e1b3c7d85a29"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "event_cards",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tree_id", sa.Integer(), sa.ForeignKey("trees.id"), nullable=False),
        sa.Column("event_id", sa.Integer(), sa.ForeignKey("events.id", ondelete="CASCADE"), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("token", sa.String(length=64), nullable=False),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("closes_on", sa.Date(), nullable=True),
        sa.Column("closed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_event_cards_tree_id", "event_cards", ["tree_id"])
    op.create_index("ix_event_cards_event_id", "event_cards", ["event_id"])
    op.create_index("ix_event_cards_token", "event_cards", ["token"], unique=True)
    op.create_table(
        "event_rsvps",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("card_id", sa.Integer(), sa.ForeignKey("event_cards.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(length=150), nullable=False),
        sa.Column("response", sa.String(length=5), nullable=True),
        sa.Column("party_size", sa.SmallInteger(), nullable=False, server_default="1"),
        sa.Column("note", sa.String(length=500), nullable=True),
        sa.Column("invitee_token", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("responded_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_event_rsvps_card_id", "event_rsvps", ["card_id"])
    op.create_index("ix_event_rsvps_invitee_token", "event_rsvps", ["invitee_token"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_event_rsvps_invitee_token", table_name="event_rsvps")
    op.drop_index("ix_event_rsvps_card_id", table_name="event_rsvps")
    op.drop_table("event_rsvps")
    op.drop_index("ix_event_cards_token", table_name="event_cards")
    op.drop_index("ix_event_cards_event_id", table_name="event_cards")
    op.drop_index("ix_event_cards_tree_id", table_name="event_cards")
    op.drop_table("event_cards")
