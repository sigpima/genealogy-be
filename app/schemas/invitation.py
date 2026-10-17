from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.schemas.calendar import LunarOut


def _blank_to_none(value: object) -> object:
    return (value.strip() or None) if isinstance(value, str) else value


class CardCreate(BaseModel):
    date: date
    message: str | None = Field(default=None, max_length=2000)
    closes_on: date | None = None

    _message = field_validator("message", mode="before")(_blank_to_none)


class CardUpdate(BaseModel):
    """PATCH: only the fields sent change (null clears the message / the deadline)."""

    message: str | None = Field(default=None, max_length=2000)
    closes_on: date | None = None
    closed: bool | None = None

    _message = field_validator("message", mode="before")(_blank_to_none)


class Counts(BaseModel):
    yes: int = 0
    no: int = 0
    maybe: int = 0
    pending: int = 0
    people: int = 0


class RsvpRead(BaseModel):
    id: int
    name: str
    response: str | None
    party_size: int
    note: str | None
    personal_token: str
    path: str
    responded_at: datetime | None


class CardRead(BaseModel):
    id: int
    event_id: int
    event_title: str
    date: date
    token: str
    path: str
    message: str | None
    closes_on: date | None
    closed: bool
    expired: bool
    counts: Counts


class CardDetail(CardRead):
    responses: list[RsvpRead]


class InviteesIn(BaseModel):
    names: list[str] = Field(max_length=200)


class RespondIn(BaseModel):
    #: Needed on the card's open link; ignored on a personal link (the guest is already named).
    name: str | None = Field(default=None, max_length=150)
    response: Literal["yes", "no", "maybe"]
    party_size: int = Field(default=1, ge=1, le=20)
    note: str | None = Field(default=None, max_length=500)

    _blank = field_validator("name", "note", mode="before")(_blank_to_none)


class PlaceInfo(BaseModel):
    name: str
    address: str | None
    latitude: float | None
    longitude: float | None


class Guest(BaseModel):
    name: str
    response: str | None
    party_size: int
    note: str | None


class PublicTotals(BaseModel):
    yes: int
    people: int


class PublicCard(BaseModel):
    family: str
    title: str
    kind: str | None
    date: date
    lunar: LunarOut
    time_text: str | None
    message: str | None
    place: PlaceInfo | None
    closed: bool
    totals: PublicTotals
    guest: Guest | None


class RespondResult(PublicCard):
    """The updated card plus the guest's own link token (kept by their browser to change the answer later)."""

    token: str
