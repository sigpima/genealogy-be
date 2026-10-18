"""The family calendar: month view, upcoming, solar<->lunar conversion, the secret .ics feed and reminder settings.
Reads follow the tree's visibility like the tree itself; managing the feed link is an admin's job."""

import calendar as _calendar
import secrets
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit, calendar_items
from app.core.calendar_items import Item, collect, count_incomplete
from app.core.ics import build_calendar
from app.core.lunar import LunarDate, lunar_to_solar, solar_to_lunar
from app.core.permissions import get_read_context, get_user_context, get_write_context
from app.core.tenancy import TreeContext
from app.db.session import get_db
from app.models.event import Event
from app.models.member import Member
from app.models.place import Place
from app.models.tree import Tree
from app.schemas.calendar import (
    CalendarDay,
    CalendarItem,
    Conversion,
    LunarOut,
    MonthView,
    ReminderSettings,
    Subscription,
    UpcomingView,
)

router = APIRouter(prefix="/calendar", tags=["calendar"])

FEED_PAST_DAYS = 30
FEED_AHEAD_DAYS = 730


def lunar_out(lunar: LunarDate) -> LunarOut:
    return LunarOut(day=lunar.day, month=lunar.month, year=lunar.year, leap=lunar.leap)


def item_out(item: Item) -> CalendarItem:
    return CalendarItem(
        date=item.date,
        kind=item.kind,
        title=item.title,
        subtitle=item.subtitle,
        lunar=lunar_out(item.lunar),
        member_id=item.member_id,
        event_id=item.event_id,
        years=item.years,
        time_text=item.time_text,
        location=item.location,
        event_kind=item.event_kind,
        description=item.description,
        place_id=item.place_id,
    )


async def load_sources(db: AsyncSession, tree_id: int) -> tuple[list[Member], list[Event], dict[int, str]]:
    members = list((await db.execute(select(Member).where(Member.tree_id == tree_id).order_by(Member.id))).scalars().all())
    events = list((await db.execute(select(Event).where(Event.tree_id == tree_id).order_by(Event.id))).scalars().all())
    names = dict((await db.execute(select(Place.id, Place.name).where(Place.tree_id == tree_id))).all())
    return members, events, names


@router.get("/month", response_model=MonthView)
async def month_view(
    year: int = Query(ge=1900, le=2100),
    month: int = Query(ge=1, le=12),
    db: AsyncSession = Depends(get_db),
    ctx: TreeContext = Depends(get_read_context),
) -> MonthView:
    first = date(year, month, 1)
    last = date(year, month, _calendar.monthrange(year, month)[1])
    members, events, places = await load_sources(db, ctx.tree.id)
    days = []
    for offset in range((last - first).days + 1):
        day = first + timedelta(days=offset)
        lunar = solar_to_lunar(day)
        days.append(CalendarDay(date=day, lunar_day=lunar.day, lunar_month=lunar.month, lunar_year=lunar.year, lunar_leap=lunar.leap))
    return MonthView(
        year=year,
        month=month,
        days=days,
        items=[item_out(i) for i in collect(members, events, first, last, places)],
        incomplete=count_incomplete(members),
    )


@router.get("/upcoming", response_model=UpcomingView)
async def upcoming(
    days: int = Query(default=30, ge=1, le=366),
    db: AsyncSession = Depends(get_db),
    ctx: TreeContext = Depends(get_read_context),
) -> UpcomingView:
    today = calendar_items.vn_today()
    members, events, places = await load_sources(db, ctx.tree.id)
    return UpcomingView(items=[item_out(i) for i in collect(members, events, today, today + timedelta(days=days), places)])


@router.get("/convert", response_model=Conversion)
async def convert(
    solar: str | None = None,
    lunar_day: int | None = Query(default=None, ge=1, le=30),
    lunar_month: int | None = Query(default=None, ge=1, le=12),
    lunar_year: int | None = Query(default=None, ge=1900, le=2100),
    lunar_leap: bool = False,
    ctx: TreeContext = Depends(get_read_context),
) -> Conversion:
    """Solar -> lunar (`solar=YYYY-MM-DD`) or lunar -> solar (`lunar_day`, `lunar_month`, `lunar_year`[, `lunar_leap`])."""
    if solar is not None:
        try:
            day = date.fromisoformat(solar)
        except ValueError:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="solar must be YYYY-MM-DD") from None
        if not 1900 <= day.year <= 2100:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="year out of range")
        return Conversion(solar=day, lunar=lunar_out(solar_to_lunar(day)))
    if lunar_day is None or lunar_month is None or lunar_year is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="give `solar`, or the lunar day, month and year")
    lunar = LunarDate(lunar_day, lunar_month, lunar_year, lunar_leap)
    day = lunar_to_solar(lunar)
    if day is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="that lunar date does not exist")
    return Conversion(solar=day, lunar=lunar_out(solar_to_lunar(day)))


# --------------------------------------------------------------------------- the secret .ics feed


def _subscription(tree: Tree) -> Subscription:
    if tree.calendar_token:
        return Subscription(enabled=True, path=f"/calendar/feed/{tree.calendar_token}.ics")
    return Subscription(enabled=False, path=None)


@router.get("/subscription", response_model=Subscription)
async def get_subscription(ctx: TreeContext = Depends(get_user_context)) -> Subscription:
    return _subscription(ctx.tree)


@router.post("/subscription", response_model=Subscription)
async def create_subscription(db: AsyncSession = Depends(get_db), ctx: TreeContext = Depends(get_write_context)) -> Subscription:
    """Enable the feed, or replace its token (anyone holding the old link stops receiving updates)."""
    action = "calendar.regenerate" if ctx.tree.calendar_token else "calendar.enable"
    ctx.tree.calendar_token = secrets.token_urlsafe(24)
    audit.record(db, tree_id=ctx.tree.id, actor=ctx.user, action=action)  # never the token itself
    await db.commit()
    return _subscription(ctx.tree)


@router.delete("/subscription", status_code=status.HTTP_204_NO_CONTENT)
async def delete_subscription(db: AsyncSession = Depends(get_db), ctx: TreeContext = Depends(get_write_context)) -> None:
    if ctx.tree.calendar_token is not None:
        audit.record(db, tree_id=ctx.tree.id, actor=ctx.user, action="calendar.disable")
    ctx.tree.calendar_token = None
    await db.commit()


@router.get("/feed/{filename}")
async def feed(filename: str, db: AsyncSession = Depends(get_db)) -> Response:
    """Public by design (a phone's calendar app sends no cookie): the secret token in the URL is the access control."""
    not_found = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not found")
    if not filename.endswith(".ics") or len(filename) < 10:
        raise not_found
    tree = (await db.execute(select(Tree).where(Tree.calendar_token == filename[: -len(".ics")]))).scalar_one_or_none()
    if tree is None:
        raise not_found
    today = calendar_items.vn_today()
    members, events, places = await load_sources(db, tree.id)
    items = collect(members, events, today - timedelta(days=FEED_PAST_DAYS), today + timedelta(days=FEED_AHEAD_DAYS), places)
    return Response(
        content=build_calendar(f"Lịch giỗ - {tree.name}", items),
        media_type="text/calendar; charset=utf-8",
        headers={"Cache-Control": "private, max-age=900"},
    )


# --------------------------------------------------------------------------- my reminder settings


def _settings_of(user) -> ReminderSettings:
    days = [int(d) for d in user.reminder_days.split(",") if d.strip()]
    return ReminderSettings(days=sorted(set(days), reverse=True), email=user.reminder_email)


@router.get("/reminders", response_model=ReminderSettings)
async def get_reminders(ctx: TreeContext = Depends(get_user_context)) -> ReminderSettings:
    return _settings_of(ctx.user)


@router.put("/reminders", response_model=ReminderSettings)
async def put_reminders(
    payload: ReminderSettings, db: AsyncSession = Depends(get_db), ctx: TreeContext = Depends(get_user_context)
) -> ReminderSettings:
    ctx.user.reminder_days = ",".join(str(d) for d in payload.days)
    ctx.user.reminder_email = payload.email
    await db.commit()
    return _settings_of(ctx.user)
