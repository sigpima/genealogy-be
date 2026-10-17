from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, SmallInteger, String, Text, false, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Event(Base):
    """A family event the admin enters by hand (a gathering, a wedding, the clan's giỗ Tổ...). Death anniversaries are
    NOT events: they are computed from the members' death dates (see app/core/calendar_items.py)."""

    __tablename__ = "events"

    id: Mapped[int] = mapped_column(primary_key=True)
    tree_id: Mapped[int] = mapped_column(ForeignKey("trees.id"), index=True, nullable=False)
    title: Mapped[str] = mapped_column(String(150), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    kind: Mapped[str] = mapped_column(String(12), nullable=False)  # gathering|wedding|birthday|memorial|other
    calendar: Mapped[str] = mapped_column(String(5), nullable=False)  # solar|lunar
    # A one-off needs its year; a repeating event may carry the year it starts.
    year: Mapped[int | None] = mapped_column(nullable=True)
    month: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    day: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    repeats_yearly: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=false())
    time_text: Mapped[str | None] = mapped_column(String(5), nullable=True)  # "HH:MM"
    location: Mapped[str | None] = mapped_column(String(255), nullable=True)
    place_id: Mapped[int | None] = mapped_column(ForeignKey("places.id", ondelete="SET NULL"), nullable=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
