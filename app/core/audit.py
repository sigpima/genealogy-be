"""The audit log: one row per change, added to the caller's transaction (the caller commits, so a change and its
log entry stand or fall together)."""

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditLog
from app.models.user import User

Values = dict[str, Any]


def diff_values(before: Values, after: Values) -> dict[str, list[Any]]:
    """{field: [old, new]} for the fields that differ."""
    return {key: [before.get(key), after.get(key)] for key in after.keys() | before.keys() if before.get(key) != after.get(key)}


def creation_changes(values: Values, defaults: Values) -> dict[str, list[Any]]:
    """What a new record was created with: every field that is not simply its default."""
    return {key: [None, value] for key, value in values.items() if key not in defaults or value != defaults[key]}


def deletion_changes(values: Values, defaults: Values) -> dict[str, list[Any]]:
    """What a deleted record held (kept so it can be restored by hand)."""
    return {key: [value, None] for key, value in values.items() if key not in defaults or value != defaults[key]}


def record(
    db: AsyncSession,
    *,
    tree_id: int,
    actor: User | None,
    action: str,
    member_id: int | None = None,
    member_name: str | None = None,
    changes: dict[str, list[Any]] | None = None,
    details: dict[str, Any] | None = None,
    request_id: int | None = None,
) -> None:
    db.add(
        AuditLog(
            tree_id=tree_id,
            actor_id=actor.id if actor else None,
            actor_name=actor.full_name if actor else "?",
            action=action,
            member_id=member_id,
            member_name=member_name,
            changes=changes or None,
            details=details or None,
            request_id=request_id,
        )
    )
