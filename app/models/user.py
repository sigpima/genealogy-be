from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, func, text, true
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models import member  # noqa: F401  (the member_id foreign key needs its target table registered)


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        Index("uq_users_member_id", "member_id", unique=True, postgresql_where=text("member_id IS NOT NULL")),
    )

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
    # Admin console: when the user last logged in (NULL = never recorded, which includes everyone from before this column existed)
    # and, optionally, which person of the tree this account is (display only; the person is deleted -> the link clears).
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    member_id: Mapped[int | None] = mapped_column(ForeignKey("members.id", ondelete="SET NULL"), nullable=True)
