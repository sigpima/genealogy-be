"""What happens on which day: giỗ computed from death dates, plus the admin's events.

Nothing here is stored per occurrence. A giỗ follows the LUNAR death date every year, so it is derived on demand; an
event is a rule (solar or lunar date, one-off or yearly) that is expanded for the range asked for.
"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from app.core.lunar import LunarDate, lunar_month_days, lunar_to_solar, solar_to_lunar
from app.models.event import Event
from app.models.member import Member

VN_TIMEZONE = timezone(timedelta(hours=7))  # Vietnam has no daylight saving


def vn_today() -> date:
    return datetime.now(VN_TIMEZONE).date()


@dataclass(frozen=True)
class Item:
    date: date
    kind: str  # death_anniversary | event
    title: str
    lunar: LunarDate
    subtitle: str | None = None
    member_id: int | None = None
    event_id: int | None = None
    #: A giỗ: how many years since the death ("giỗ lần thứ N"; 1 = giỗ đầu). None when the death year is unknown.
    years: int | None = None
    time_text: str | None = None
    location: str | None = None
    event_kind: str | None = None
    description: str | None = None
    place_id: int | None = None


def lunar_text(lunar: LunarDate) -> str:
    return f"{lunar.day}/{lunar.month}{' nhuận' if lunar.leap else ''} âm lịch"


def death_lunar(member: Member) -> tuple[int, int, int | None] | None:
    """(day, month, lunar year or None) of the death, or None when it cannot be known.

    A lunar death date is taken as entered. A solar one is converted once, but only with a full date: month and day
    alone cannot be converted because the lunar date of a solar day changes every year.
    """
    if member.death_month is None or member.death_day is None:
        return None
    if member.death_is_lunar:
        return member.death_day, member.death_month, member.death_year
    if member.death_year is None:
        return None
    try:
        lunar = solar_to_lunar(date(member.death_year, member.death_month, member.death_day))
    except ValueError:
        return None
    return lunar.day, lunar.month, lunar.year


def count_incomplete(members: list[Member]) -> int:
    """People with a death month and day we still cannot turn into a giỗ (solar date without a year)."""
    return sum(1 for m in members if m.death_month is not None and m.death_day is not None and death_lunar(m) is None)


def _lunar_years(start: date, end: date) -> range:
    # a solar range touches the lunar year of its ends, and one more on each side for Dec/Jan boundaries
    return range(solar_to_lunar(start).year - 1, solar_to_lunar(end).year + 2)


def _lunar_occurrence(day: int, month: int, lunar_year: int) -> date | None:
    """The solar date of a lunar day/month in a year. Regular month only; day 30 in a 29-day month is day 29."""
    length = lunar_month_days(month, lunar_year)
    if length is None:
        return None
    return lunar_to_solar(LunarDate(min(day, length), month, lunar_year, False))


def anniversaries(members: list[Member], start: date, end: date) -> list[Item]:
    items = []
    for member in members:
        known = death_lunar(member)
        if known is None:
            continue
        day, month, death_year = known
        for lunar_year in _lunar_years(start, end):
            if death_year is not None and lunar_year <= death_year:
                continue  # the year of the death is not an anniversary
            solar = _lunar_occurrence(day, month, lunar_year)
            if solar is None or not start <= solar <= end:
                continue
            lunar = solar_to_lunar(solar)
            years = lunar_year - death_year if death_year is not None else None
            subtitle = lunar_text(lunar) + (f" · giỗ lần thứ {years}" if years else "")
            items.append(
                Item(
                    date=solar,
                    kind="death_anniversary",
                    title=f"Giỗ {member.full_name}",
                    lunar=lunar,
                    subtitle=subtitle,
                    member_id=member.id,
                    years=years,
                )
            )
    return items


def event_items(events: list[Event], start: date, end: date, places: dict[int, str] | None = None) -> list[Item]:
    items = []
    places = places or {}
    for event in events:
        candidates: list[date | None] = []
        if event.calendar == "solar":
            years = range(start.year, end.year + 1) if event.repeats_yearly else [event.year]
            for year in years:
                if event.repeats_yearly and event.year is not None and year < event.year:
                    continue
                try:
                    candidates.append(date(year, event.month, event.day))
                except ValueError:  # 29 February in a common year
                    continue
        else:
            years = _lunar_years(start, end) if event.repeats_yearly else [event.year]
            for lunar_year in years:
                if event.repeats_yearly and event.year is not None and lunar_year < event.year:
                    continue
                candidates.append(_lunar_occurrence(event.day, event.month, lunar_year))
        for solar in candidates:
            if solar is None or not start <= solar <= end:
                continue
            lunar = solar_to_lunar(solar)
            items.append(
                Item(
                    date=solar,
                    kind="event",
                    title=event.title,
                    lunar=lunar,
                    subtitle=lunar_text(lunar),
                    event_id=event.id,
                    time_text=event.time_text,
                    location=event.location or places.get(event.place_id or 0),
                    event_kind=event.kind,
                    description=event.description,
                    place_id=event.place_id,
                )
            )
    return items


def collect(
    members: list[Member], events: list[Event], start: date, end: date, places: dict[int, str] | None = None
) -> list[Item]:
    """Everything in [start, end], in calendar order."""
    items = anniversaries(members, start, end) + event_items(events, start, end, places)
    return sorted(items, key=lambda i: (i.date, i.kind != "event", i.title, i.member_id or 0, i.event_id or 0))
