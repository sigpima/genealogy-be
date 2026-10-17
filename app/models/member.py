from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, SmallInteger, String, Text, false, func, true
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Member(Base):
    __tablename__ = "members"

    id: Mapped[int] = mapped_column(primary_key=True)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    tree_id: Mapped[int] = mapped_column(ForeignKey("trees.id"), index=True, nullable=False)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("members.id"), nullable=True)
    birth_year: Mapped[int | None] = mapped_column(nullable=True)
    death_year: Mapped[int | None] = mapped_column(nullable=True)
    gender: Mapped[str | None] = mapped_column(String(10), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    courtesy_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    title: Mapped[str | None] = mapped_column(String(150), nullable=True)
    residence: Mapped[str | None] = mapped_column(String(255), nullable=True)
    burial_place: Mapped[str | None] = mapped_column(String(500), nullable=True)
    burial_latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    burial_longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    hometown: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(30), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Partial dates: year may be unknown while month/day are known (a giỗ needs only the lunar month+day).
    birth_month: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    birth_day: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    death_month: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    death_day: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    birth_is_lunar: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=false())
    birth_leap_month: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=false())
    death_is_lunar: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=true())
    death_leap_month: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=false())
    birth_order: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)  # manual order among siblings
    is_adopted: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=false())
    # The mother must be a recorded spouse of the father (parent_id); checked by the API, not the DB.
    # GĐ6: where the person rests (a place of the tree) and the spot in it ("khu B, hàng 3, mộ 12").
    burial_place_id: Mapped[int | None] = mapped_column(ForeignKey("places.id", ondelete="SET NULL"), nullable=True)
    burial_plot: Mapped[str | None] = mapped_column(String(100), nullable=True)
    mother_id: Mapped[int | None] = mapped_column(ForeignKey("members.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
