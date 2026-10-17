from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, func, true
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    # role: "superadmin" | "admin" | "member"; status: "pending" | "active" | "disabled" (app/core/roles.py)
    # tree_id: the one tree a user belongs to; NULL only for superadmins (platform level).
    tree_id: Mapped[int | None] = mapped_column(ForeignKey("trees.id"), index=True, nullable=True)
    role: Mapped[str] = mapped_column(String(10), nullable=False, server_default="member")
    status: Mapped[str] = mapped_column(String(10), nullable=False, server_default="active")
    # Reminders (GĐ5): which days before a giỗ/event to be notified ("7,1"), and whether to email as well.
    reminder_days: Mapped[str] = mapped_column(String(40), nullable=False, server_default="7,1")
    reminder_email: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=true())
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
