from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models import user  # noqa: F401  (the actor_id foreign key needs its target table registered)


class PlatformEvent(Base):
    """What the superadmin did to the families (create, pause, delete, admin changes, going in). Its own table, not the
    families' audit log: a deleted family has no tree to hold its entries, and tree admins must never read these.
    `tree_id` has no foreign key on purpose, `tree_name` keeps who it was."""

    __tablename__ = "platform_events"
    __table_args__ = (Index("ix_platform_events_created_at", "created_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    actor_name: Mapped[str] = mapped_column(String(255), nullable=False)
    action: Mapped[str] = mapped_column(String(40), nullable=False)
    tree_id: Mapped[int | None] = mapped_column(nullable=True)
    tree_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    details: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
