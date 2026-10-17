"""gd6 media and places

Revision ID: d9a2b4c61e37
Revises: c5e8a1f03d92
Create Date: 2026-10-18 23:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d9a2b4c61e37"
down_revision: Union[str, Sequence[str], None] = "c5e8a1f03d92"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "places",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tree_id", sa.Integer(), sa.ForeignKey("trees.id"), nullable=False),
        sa.Column("kind", sa.String(length=12), nullable=False),
        sa.Column("name", sa.String(length=150), nullable=False),
        sa.Column("address", sa.String(length=500), nullable=True),
        sa.Column("latitude", sa.Float(), nullable=True),
        sa.Column("longitude", sa.Float(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("caretaker", sa.String(length=255), nullable=True),
        sa.Column("visit_notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_places_tree_id", "places", ["tree_id"])
    op.create_table(
        "media",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tree_id", sa.Integer(), sa.ForeignKey("trees.id"), nullable=False),
        sa.Column("member_id", sa.Integer(), sa.ForeignKey("members.id", ondelete="CASCADE"), nullable=True),
        sa.Column("place_id", sa.Integer(), sa.ForeignKey("places.id", ondelete="CASCADE"), nullable=True),
        sa.Column("kind", sa.String(length=10), nullable=False),
        sa.Column("original_name", sa.String(length=255), nullable=False),
        sa.Column("content_type", sa.String(length=50), nullable=False),
        sa.Column("size", sa.Integer(), nullable=False),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("stored_name", sa.String(length=60), nullable=False, unique=True),
        sa.Column("thumb_name", sa.String(length=60), nullable=True, unique=True),
        sa.Column("caption", sa.Text(), nullable=True),
        sa.Column("uploaded_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_media_tree_id", "media", ["tree_id"])
    op.create_index("ix_media_member_id", "media", ["member_id"])
    op.create_index("ix_media_place_id", "media", ["place_id"])
    op.add_column("members", sa.Column("burial_place_id", sa.Integer(), nullable=True))
    op.create_foreign_key("members_burial_place_id_fkey", "members", "places", ["burial_place_id"], ["id"], ondelete="SET NULL")
    op.add_column("members", sa.Column("burial_plot", sa.String(length=100), nullable=True))
    op.add_column("events", sa.Column("place_id", sa.Integer(), nullable=True))
    op.create_foreign_key("events_place_id_fkey", "events", "places", ["place_id"], ["id"], ondelete="SET NULL")


def downgrade() -> None:
    op.drop_constraint("events_place_id_fkey", "events", type_="foreignkey")
    op.drop_column("events", "place_id")
    op.drop_column("members", "burial_plot")
    op.drop_constraint("members_burial_place_id_fkey", "members", type_="foreignkey")
    op.drop_column("members", "burial_place_id")
    op.drop_index("ix_media_place_id", table_name="media")
    op.drop_index("ix_media_member_id", table_name="media")
    op.drop_index("ix_media_tree_id", table_name="media")
    op.drop_table("media")
    op.drop_index("ix_places_tree_id", table_name="places")
    op.drop_table("places")
