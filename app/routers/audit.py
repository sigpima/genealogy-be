"""The change log, newest first (admins of the tree only)."""

import datetime
from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit_kinds import action_filter, day_after, day_start
from app.core.permissions import get_write_context
from app.core.tenancy import TreeContext
from app.db.session import get_db
from app.models.audit_log import AuditLog
from app.models.user import User
from app.schemas.audit import AuditActor, AuditEntry, AuditPage

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("", response_model=AuditPage)
async def list_audit(
    member_id: int | None = None,
    actor_id: int | None = None,
    kind: Literal["data", "people", "security", "settings"] | None = None,
    since: datetime.date | None = None,
    until: datetime.date | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    ctx: TreeContext = Depends(get_write_context),
) -> AuditPage:
    conditions = [AuditLog.tree_id == ctx.tree.id]
    if member_id is not None:
        conditions.append(AuditLog.member_id == member_id)
    if actor_id is not None:
        conditions.append(AuditLog.actor_id == actor_id)
    if kind is not None:
        conditions.append(action_filter(kind))
    if since is not None:  # whole days in Vietnam time, both ends inclusive
        conditions.append(AuditLog.created_at >= day_start(since))
    if until is not None:
        conditions.append(AuditLog.created_at < day_after(until))
    total = (await db.execute(select(func.count()).select_from(AuditLog).where(*conditions))).scalar_one()
    rows = (
        await db.execute(
            select(AuditLog, User.role)
            .outerjoin(User, User.id == AuditLog.actor_id)
            .where(*conditions)
            .order_by(AuditLog.id.desc())
            .limit(limit)
            .offset(offset)
        )
    ).all()
    items = []
    for row, role in rows:
        entry = AuditEntry.model_validate(row, from_attributes=True)
        entry.actor_role = role
        items.append(entry)
    return AuditPage(total=total, items=items)


@router.get("/actors", response_model=list[AuditActor])
async def list_actors(db: AsyncSession = Depends(get_db), ctx: TreeContext = Depends(get_write_context)) -> list[AuditActor]:
    """Everybody who has made an entry in this family's log (for the "Người thực hiện" filter), by name."""
    rows = (
        await db.execute(
            select(User.id, User.full_name, User.role)
            .where(User.id.in_(select(AuditLog.actor_id).where(AuditLog.tree_id == ctx.tree.id, AuditLog.actor_id.is_not(None))))
            .order_by(User.full_name, User.id)
        )
    ).all()
    return [AuditActor(id=i, name=name, role=role) for i, name, role in rows]
