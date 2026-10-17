"""Family events (admin-entered). Giỗ are not events: they are computed from death dates."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.core.audit import diff_values
from app.core.permissions import get_read_context, get_write_context
from app.core.tenancy import TreeContext
from app.db.session import get_db
from app.models.event import Event
from app.schemas.calendar import EventCreate, EventRead, EventUpdate

router = APIRouter(prefix="/events", tags=["events"])

FIELDS = ("title", "kind", "calendar", "year", "month", "day", "repeats_yearly", "time_text", "location", "description")


def _values(event: Event) -> dict:
    return {name: getattr(event, name) for name in FIELDS}


async def _in_tree(db: AsyncSession, ctx: TreeContext, event_id: int) -> Event:
    event = await db.get(Event, event_id)
    if event is None or event.tree_id != ctx.tree.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="event not found")
    return event


@router.get("", response_model=list[EventRead])
async def list_events(db: AsyncSession = Depends(get_db), ctx: TreeContext = Depends(get_read_context)) -> list[Event]:
    return list((await db.execute(select(Event).where(Event.tree_id == ctx.tree.id).order_by(Event.id))).scalars().all())


@router.post("", response_model=EventRead, status_code=status.HTTP_201_CREATED)
async def create_event(payload: EventCreate, db: AsyncSession = Depends(get_db), ctx: TreeContext = Depends(get_write_context)) -> Event:
    event = Event(tree_id=ctx.tree.id, created_by=ctx.user.id, **payload.model_dump())
    db.add(event)
    await db.flush()
    audit.record(
        db,
        tree_id=ctx.tree.id,
        actor=ctx.user,
        action="event.create",
        changes={k: [None, v] for k, v in _values(event).items() if v not in (None, False)},
        details={"event_id": event.id, "title": event.title},
    )
    await db.commit()
    await db.refresh(event)
    return event


@router.put("/{event_id}", response_model=EventRead)
async def update_event(
    event_id: int, payload: EventUpdate, db: AsyncSession = Depends(get_db), ctx: TreeContext = Depends(get_write_context)
) -> Event:
    event = await _in_tree(db, ctx, event_id)
    before = _values(event)
    for name, value in payload.model_dump().items():
        setattr(event, name, value)
    changes = diff_values(before, _values(event))
    if changes:
        audit.record(
            db, tree_id=ctx.tree.id, actor=ctx.user, action="event.update", changes=changes,
            details={"event_id": event.id, "title": event.title},
        )
    await db.commit()
    await db.refresh(event)
    return event


@router.delete("/{event_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_event(event_id: int, db: AsyncSession = Depends(get_db), ctx: TreeContext = Depends(get_write_context)) -> None:
    event = await _in_tree(db, ctx, event_id)
    audit.record(
        db,
        tree_id=ctx.tree.id,
        actor=ctx.user,
        action="event.delete",
        changes={k: [v, None] for k, v in _values(event).items() if v not in (None, False)},
        details={"event_id": event.id, "title": event.title},
    )
    await db.delete(event)
    await db.commit()
