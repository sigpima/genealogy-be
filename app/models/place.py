from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Place(Base):
    """A place of the family: nhà thờ họ, từ đường, lăng mộ, nghĩa trang, đền. Members point at it with
    `members.burial_place_id` (their resting place) and events with `events.place_id`."""

    __tablename__ = "places"

    id: Mapped[int] = mapped_column(primary_key=True)
    tree_id: Mapped[int] = mapped_column(ForeignKey("trees.id"), index=True, nullable=False)
    kind: Mapped[str] = mapped_column(String(12), nullable=False)  # clan_house|temple|tomb|cemetery|other
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    address: Mapped[str | None] = mapped_column(String(500), nullable=True)
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    map_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    caretaker: Mapped[str | None] = mapped_column(String(255), nullable=True)
    visit_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
