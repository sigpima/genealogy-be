"""The change log, newest first (admins of the tree only)."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import get_write_context
from app.core.tenancy import TreeContext
from app.db.session import get_db
from app.models.audit_log import AuditLog
from app.schemas.audit import AuditEntry, AuditPage

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("", response_model=AuditPage)
async def list_audit(
    member_id: int | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    ctx: TreeContext = Depends(get_write_context),
) -> AuditPage:
    conditions = [AuditLog.tree_id == ctx.tree.id]
    if member_id is not None:
        conditions.append(AuditLog.member_id == member_id)
    total = (await db.execute(select(func.count()).select_from(AuditLog).where(*conditions))).scalar_one()
    rows = (
        await db.execute(
            select(AuditLog).where(*conditions).order_by(AuditLog.id.desc()).limit(limit).offset(offset)
        )
    ).scalars().all()
    return AuditPage(total=total, items=[AuditEntry.model_validate(r, from_attributes=True) for r in rows])
