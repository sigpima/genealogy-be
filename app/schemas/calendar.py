import re
from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

EVENT_KINDS = ("gathering", "wedding", "birthday", "memorial", "other")
REMINDER_DAYS_ALLOWED = (0, 1, 3, 7, 14, 30)
_TIME = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


class LunarOut(BaseModel):
    day: int
    month: int
    year: int
    leap: bool


class CalendarItem(BaseModel):
    date: date
    kind: Literal["death_anniversary", "event"]
    title: str
    subtitle: str | None
    lunar: LunarOut
    member_id: int | None
    event_id: int | None
    years: int | None
    time_text: str | None
    location: str | None
    event_kind: str | None
    description: str | None


class CalendarDay(BaseModel):
    date: date
    lunar_day: int
    lunar_month: int
    lunar_year: int
    lunar_leap: bool


class MonthView(BaseModel):
    year: int
    month: int
    days: list[CalendarDay]
    items: list[CalendarItem]
    #: People with a death month and day we cannot turn into a giỗ (a solar date without a year).
    incomplete: int


class UpcomingView(BaseModel):
    items: list[CalendarItem]


class Conversion(BaseModel):
    solar: date
    lunar: LunarOut


class EventBase(BaseModel):
    title: str = Field(max_length=150)
    kind: Literal["gathering", "wedding", "birthday", "memorial", "other"]
    calendar: Literal["solar", "lunar"]
    year: int | None = Field(default=None, ge=1000, le=9999)
    month: int = Field(ge=1, le=12)
    day: int = Field(ge=1, le=31)
    repeats_yearly: bool = False
    time_text: str | None = None
    location: str | None = Field(default=None, max_length=255)
    description: str | None = Field(default=None, max_length=5000)

    @field_validator("title")
    @classmethod
    def _title(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("title must not be empty")
        return value

    @field_validator("location", "description", "time_text", mode="before")
    @classmethod
    def _blank_to_none(cls, value: object) -> object:
        if isinstance(value, str):
            value = value.strip()
            return value or None
        return value

    @field_validator("time_text")
    @classmethod
    def _time(cls, value: str | None) -> str | None:
        if value is not None and not _TIME.match(value):
            raise ValueError("time must look like 08:30")
        return value

    @model_validator(mode="after")
    def _check_date(self) -> "EventBase":
        if not self.repeats_yearly and self.year is None:
            raise ValueError("a one-off event needs its year")
        if self.calendar == "lunar":
            if self.day > 30:
                raise ValueError("a lunar month has at most 30 days")
        else:
            try:  # 2000 is a leap year, so a yearly 29 February is accepted when no year is fixed
                date(self.year if self.year is not None else 2000, self.month, self.day)
            except ValueError:
                raise ValueError("that day does not exist in that month") from None
        return self


class EventCreate(EventBase):
    pass


class EventUpdate(EventBase):
    """PUT replaces the event."""


class EventRead(EventBase):
    id: int


class Subscription(BaseModel):
    enabled: bool
    #: Path of the feed below the API root (the web app serves it under /api); null while disabled.
    path: str | None


class ReminderSettings(BaseModel):
    days: list[int]
    email: bool

    @field_validator("days")
    @classmethod
    def _days(cls, value: list[int]) -> list[int]:
        if any(d not in REMINDER_DAYS_ALLOWED for d in value):
            raise ValueError(f"days must be among {REMINDER_DAYS_ALLOWED}")
        return sorted(set(value), reverse=True)


class NotificationRead(BaseModel):
    id: int
    kind: str
    title: str
    body: str | None
    link: str | None
    created_at: str
    read: bool


class NotificationList(BaseModel):
    unread: int
    items: list[NotificationRead]


class MarkRead(BaseModel):
    #: Omit to mark everything read.
    ids: list[int] | None = None
