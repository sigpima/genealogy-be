"""Platform level (superadmin only): overview, platform log, system health. Independent of the tree the superadmin currently acts on."""

import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit_kinds import day_after, day_start

from app.core.permissions import require_superadmin
from app.core.platform_overview import compute_platform_overview
from app.db.session import get_db
from app.models.platform_event import PlatformEvent
from app.schemas.platform import PlatformEventPage, PlatformEventRead, PlatformOverview

router = APIRouter(prefix="/platform", tags=["platform"], dependencies=[Depends(require_superadmin)])


@router.get("/overview", response_model=PlatformOverview)
async def overview(db: AsyncSession = Depends(get_db)) -> PlatformOverview:
    return await compute_platform_overview(db)


@router.get("/events", response_model=PlatformEventPage)
async def list_events(
    action: str | None = None,
    tree_id: int | None = None,
    since: datetime.date | None = None,
    until: datetime.date | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> PlatformEventPage:
    """The platform log, newest first. `action` is a prefix ("tree." / "support"); dates are whole days in Vietnam time, inclusive."""
    conditions = []
    if action:
        conditions.append(PlatformEvent.action.like(f"{action}%"))
    if tree_id is not None:
        conditions.append(PlatformEvent.tree_id == tree_id)
    if since is not None:
        conditions.append(PlatformEvent.created_at >= day_start(since))
    if until is not None:
        conditions.append(PlatformEvent.created_at < day_after(until))
    total = (await db.execute(select(func.count()).select_from(PlatformEvent).where(*conditions))).scalar_one()
    rows = (
        await db.execute(select(PlatformEvent).where(*conditions).order_by(PlatformEvent.id.desc()).limit(limit).offset(offset))
    ).scalars().all()
    return PlatformEventPage(total=total, items=[PlatformEventRead.model_validate(r, from_attributes=True) for r in rows])
