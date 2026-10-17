from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, SmallInteger, String, Text, func, false
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class EventCard(Base):
    """An invitation for ONE occurrence of an event (a yearly giỗ Tổ needs its date). Its secret `token` is the open link
    that anyone may use to answer without logging in (see the GĐ9 design)."""

    __tablename__ = "event_cards"

    id: Mapped[int] = mapped_column(primary_key=True)
    tree_id: Mapped[int] = mapped_column(ForeignKey("trees.id"), index=True, nullable=False)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"), index=True, nullable=False)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    token: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    closes_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    closed: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=false())
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class EventRsvp(Base):
    """One guest's answer (NULL response = invited but silent). `invitee_token` is the guest's own link."""

    __tablename__ = "event_rsvps"

    id: Mapped[int] = mapped_column(primary_key=True)
    card_id: Mapped[int] = mapped_column(ForeignKey("event_cards.id", ondelete="CASCADE"), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    response: Mapped[str | None] = mapped_column(String(5), nullable=True)  # yes | no | maybe
    party_size: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="1")
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    invitee_token: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
