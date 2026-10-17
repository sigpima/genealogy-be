from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ChangeRequest(Base):
    """A member's proposal that an admin reviews (see the GĐ4 design). `changes` are the proposed field values,
    `base` the person's values for those fields when it was sent (to spot a tree that moved on since)."""

    __tablename__ = "change_requests"

    id: Mapped[int] = mapped_column(primary_key=True)
    tree_id: Mapped[int] = mapped_column(ForeignKey("trees.id"), index=True, nullable=False)
    # The person concerned (for add_child: the parent). SET NULL keeps the request when they are deleted.
    member_id: Mapped[int | None] = mapped_column(ForeignKey("members.id", ondelete="SET NULL"), nullable=True)
    member_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    requester_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True, nullable=True)
    requester_name: Mapped[str] = mapped_column(String(255), nullable=False)
    kind: Mapped[str] = mapped_column(String(10), nullable=False)  # edit | add_child | report
    status: Mapped[str] = mapped_column(String(10), nullable=False, server_default="pending")
    changes: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    base: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewer_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    reviewer_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    result_member_id: Mapped[int | None] = mapped_column(ForeignKey("members.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
