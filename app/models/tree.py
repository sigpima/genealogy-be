from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Tree(Base):
    """One family's tree. Members, settings and users all hang off a tree (see multi-tree design)."""

    __tablename__ = "trees"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(60), unique=True, index=True, nullable=False)
    # Secret of the calendar's .ics feed URL (NULL = feed disabled); an admin creates/regenerates/removes it.
    calendar_token: Mapped[str | None] = mapped_column(String(64), unique=True, index=True, nullable=True)
    # "active" | "paused": a paused family is stopped for everybody in it (login, sessions, guests, public links, reminders);
    # the superadmin can still look at it and act on it. See app/core/tenancy.py::is_paused.
    status: Mapped[str] = mapped_column(String(10), nullable=False, server_default="active")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
