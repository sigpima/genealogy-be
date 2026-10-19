from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models import change_request  # noqa: F401  (the request_id foreign key needs its target table registered)


class AuditLog(Base):
    """Who changed what, when. Written in the same transaction as the change itself. `member_id` has no foreign key
    on purpose: the entries of a deleted person must survive (with `member_name` as the record of who it was)."""

    __tablename__ = "audit_log"
    __table_args__ = (Index("ix_audit_log_tree_id_id", "tree_id", "id"),)  # the log page: newest first within one family

    id: Mapped[int] = mapped_column(primary_key=True)
    tree_id: Mapped[int] = mapped_column(ForeignKey("trees.id"), index=True, nullable=False)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    actor_name: Mapped[str] = mapped_column(String(255), nullable=False)
    action: Mapped[str] = mapped_column(String(40), nullable=False)  # member.create, branch.update, request.approve...
    member_id: Mapped[int | None] = mapped_column(index=True, nullable=True)
    member_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    changes: Mapped[dict | None] = mapped_column(JSONB, nullable=True)  # {field: [old, new]}
    details: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    request_id: Mapped[int | None] = mapped_column(ForeignKey("change_requests.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
