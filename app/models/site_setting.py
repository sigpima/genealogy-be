from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class SiteSetting(Base):
    """Per-tree key/value configuration (see app/core/roles.py for the keys and allowed values)."""

    __tablename__ = "site_settings"

    tree_id: Mapped[int] = mapped_column(
        ForeignKey("trees.id", ondelete="CASCADE"), primary_key=True
    )
    key: Mapped[str] = mapped_column(String(50), primary_key=True)
    value: Mapped[str] = mapped_column(String(255), nullable=False)
