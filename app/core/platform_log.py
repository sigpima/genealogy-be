"""The platform log: one row per thing the superadmin did to the families. Added to the caller's transaction (the caller commits)."""

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.platform_event import PlatformEvent
from app.models.tree import Tree
from app.models.user import User


def record(
    db: AsyncSession,
    *,
    actor: User,
    action: str,
    tree: Tree | None = None,
    tree_id: int | None = None,
    tree_name: str | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    """Never put a password, token or hash in `details`."""
    db.add(
        PlatformEvent(
            actor_id=actor.id,
            actor_name=actor.full_name,
            action=action,
            tree_id=tree.id if tree is not None else tree_id,
            tree_name=tree.name if tree is not None else tree_name,
            details=details or None,
        )
    )
