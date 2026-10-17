from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Branch(Base):
    """A chi/phái: the subtree below `root_member_id` (see the GĐ3 design). A person's branch is the deepest
    branch whose head is that person or one of their ancestors, so nothing is stored per member."""

    __tablename__ = "branches"

    id: Mapped[int] = mapped_column(primary_key=True)
    tree_id: Mapped[int] = mapped_column(ForeignKey("trees.id"), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    color: Mapped[str] = mapped_column(String(7), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # A head can only be deleted while it has no children, and then its branch has nothing left: cascade.
    root_member_id: Mapped[int] = mapped_column(
        ForeignKey("members.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
