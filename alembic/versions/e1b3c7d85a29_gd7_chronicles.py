"""gd7 chronicles: articles, timeline, generation words

Revision ID: e1b3c7d85a29
Revises: d9a2b4c61e37
Create Date: 2026-10-19 09:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e1b3c7d85a29"
down_revision: Union[str, Sequence[str], None] = "d9a2b4c61e37"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "articles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tree_id", sa.Integer(), sa.ForeignKey("trees.id"), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("slug", sa.String(length=120), nullable=False),
        sa.Column("kind", sa.String(length=10), nullable=False),
        sa.Column("body", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.String(length=10), nullable=False, server_default="draft"),
        sa.Column("pinned", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cover_media_id", sa.Integer(), nullable=True),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("tree_id", "slug", name="uq_articles_tree_slug"),
    )
    op.create_index("ix_articles_tree_id", "articles", ["tree_id"])
    op.add_column("media", sa.Column("article_id", sa.Integer(), nullable=True))
    op.create_foreign_key("media_article_id_fkey", "media", "articles", ["article_id"], ["id"], ondelete="CASCADE")
    op.create_index("ix_media_article_id", "media", ["article_id"])
    op.create_foreign_key("articles_cover_media_id_fkey", "articles", "media", ["cover_media_id"], ["id"], ondelete="SET NULL")
    op.create_table(
        "article_members",
        sa.Column("article_id", sa.Integer(), sa.ForeignKey("articles.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("member_id", sa.Integer(), sa.ForeignKey("members.id", ondelete="CASCADE"), primary_key=True),
    )
    op.create_index("ix_article_members_member_id", "article_members", ["member_id"])
    op.create_table(
        "timeline_entries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tree_id", sa.Integer(), sa.ForeignKey("trees.id"), nullable=False),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("month", sa.SmallInteger(), nullable=True),
        sa.Column("day", sa.SmallInteger(), nullable=True),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("member_id", sa.Integer(), sa.ForeignKey("members.id", ondelete="SET NULL"), nullable=True),
        sa.Column("article_id", sa.Integer(), sa.ForeignKey("articles.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_timeline_entries_tree_id", "timeline_entries", ["tree_id"])
    op.create_table(
        "generation_words",
        sa.Column("tree_id", sa.Integer(), sa.ForeignKey("trees.id"), primary_key=True),
        sa.Column("generation", sa.Integer(), primary_key=True),
        sa.Column("word", sa.String(length=60), nullable=False),
        sa.Column("meaning", sa.String(length=500), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("generation_words")
    op.drop_index("ix_timeline_entries_tree_id", table_name="timeline_entries")
    op.drop_table("timeline_entries")
    op.drop_index("ix_article_members_member_id", table_name="article_members")
    op.drop_table("article_members")
    op.drop_constraint("articles_cover_media_id_fkey", "articles", type_="foreignkey")
    op.drop_index("ix_media_article_id", table_name="media")
    op.drop_constraint("media_article_id_fkey", "media", type_="foreignkey")
    op.drop_column("media", "article_id")
    op.drop_index("ix_articles_tree_id", table_name="articles")
    op.drop_table("articles")
