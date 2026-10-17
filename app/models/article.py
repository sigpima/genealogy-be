from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, SmallInteger, String, Text, UniqueConstraint, func, false
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Article(Base):
    """A piece of the family's written memory (origin story, tộc ước, a person's story...). Markdown body; `members` are
    the people it mentions (see ArticleMember). Photos are `media` rows with this article's id."""

    __tablename__ = "articles"
    __table_args__ = (UniqueConstraint("tree_id", "slug", name="uq_articles_tree_slug"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    tree_id: Mapped[int] = mapped_column(ForeignKey("trees.id"), index=True, nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(120), nullable=False)
    kind: Mapped[str] = mapped_column(String(10), nullable=False)  # origin|lineage|precepts|event|person|other
    body: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    status: Mapped[str] = mapped_column(String(10), nullable=False, server_default="draft")  # draft|published
    pinned: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=false())
    position: Mapped[int] = mapped_column(nullable=False, server_default="0")
    # use_alter: media.article_id points back at articles, so this foreign key is added after both tables exist.
    cover_media_id: Mapped[int | None] = mapped_column(
        ForeignKey("media.id", ondelete="SET NULL", use_alter=True, name="articles_cover_media_id_fkey"), nullable=True
    )
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class ArticleMember(Base):
    """Which people an article mentions (chosen by the admin; nothing is parsed out of the text)."""

    __tablename__ = "article_members"

    article_id: Mapped[int] = mapped_column(ForeignKey("articles.id", ondelete="CASCADE"), primary_key=True)
    member_id: Mapped[int] = mapped_column(ForeignKey("members.id", ondelete="CASCADE"), primary_key=True, index=True)


class TimelineEntry(Base):
    """One line of the clan's own history."""

    __tablename__ = "timeline_entries"

    id: Mapped[int] = mapped_column(primary_key=True)
    tree_id: Mapped[int] = mapped_column(ForeignKey("trees.id"), index=True, nullable=False)
    year: Mapped[int] = mapped_column(nullable=False)
    month: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    day: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    member_id: Mapped[int | None] = mapped_column(ForeignKey("members.id", ondelete="SET NULL"), nullable=True)
    article_id: Mapped[int | None] = mapped_column(ForeignKey("articles.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class GenerationWord(Base):
    """Bài đệm / tự bối: the middle-name word the clan assigns to a generation."""

    __tablename__ = "generation_words"

    tree_id: Mapped[int] = mapped_column(ForeignKey("trees.id"), primary_key=True)
    generation: Mapped[int] = mapped_column(primary_key=True)
    word: Mapped[str] = mapped_column(String(60), nullable=False)
    meaning: Mapped[str | None] = mapped_column(String(500), nullable=True)
