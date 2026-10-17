import re
from datetime import date, datetime
from enum import Enum

from email_validator import EmailNotValidError, validate_email
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Gender(str, Enum):
    male = "male"
    female = "female"
    other = "other"


PHONE_PATTERN = re.compile(r"^[0-9+\-(). ]+$")


def _check_partial_date(
    prefix: str, year: int | None, month: int | None, day: int | None, is_lunar: bool, leap: bool
) -> None:
    """A month/day may be known without a year (a giỗ needs only the lunar month+day)."""
    if day is not None and month is None:
        raise ValueError(f"{prefix}_day needs {prefix}_month")
    if leap and not (is_lunar and month is not None):
        raise ValueError(f"{prefix}_leap_month needs a lunar {prefix}_month")
    if day is None:
        return
    if day < 1 or day > (30 if is_lunar else 31):
        raise ValueError(f"{prefix}_day is out of range for a {'lunar' if is_lunar else 'solar'} month")
    if not is_lunar and year is not None and 1 <= year <= 9999:
        try:
            date(year, month, day)
        except ValueError:
            raise ValueError(f"{prefix} date {year}-{month:02d}-{day:02d} does not exist") from None


class _ProfileFields(BaseModel):
    """Fields shared by create and update: cleaned strings, partial dates, GPS both-or-neither, relations."""

    hometown: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=30)
    email: str | None = Field(default=None, max_length=255)
    birth_month: int | None = Field(default=None, ge=1, le=12)
    birth_day: int | None = Field(default=None, ge=1, le=31)
    death_month: int | None = Field(default=None, ge=1, le=12)
    death_day: int | None = Field(default=None, ge=1, le=31)
    birth_is_lunar: bool = False
    birth_leap_month: bool = False
    death_is_lunar: bool = True  # a death date is mostly kept for the giỗ, which is lunar
    death_leap_month: bool = False
    birth_order: int | None = Field(default=None, ge=1)
    is_adopted: bool = False
    mother_id: int | None = None

    courtesy_name: str | None = Field(default=None, max_length=100)
    title: str | None = Field(default=None, max_length=150)
    residence: str | None = Field(default=None, max_length=255)
    burial_place: str | None = Field(default=None, max_length=500)
    burial_latitude: float | None = Field(default=None, ge=-90, le=90)
    burial_longitude: float | None = Field(default=None, ge=-180, le=180)

    @field_validator("courtesy_name", "title", "residence", "burial_place", "hometown", "phone", "email", mode="before")
    @classmethod
    def _blank_to_none(cls, value: object) -> object:
        if isinstance(value, str):
            value = value.strip()
            return value or None
        return value

    @field_validator("phone")
    @classmethod
    def _check_phone(cls, value: str | None) -> str | None:
        if value is not None and not PHONE_PATTERN.match(value):
            raise ValueError("phone may only contain digits and + - ( ) . and spaces")
        return value

    @field_validator("email")
    @classmethod
    def _check_email(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            validate_email(value, check_deliverability=False)
        except EmailNotValidError as exc:
            raise ValueError(f"invalid email: {exc}") from None
        return value

    @model_validator(mode="after")
    def _check_gps(self) -> "_ProfileFields":
        if (self.burial_latitude is None) != (self.burial_longitude is None):
            raise ValueError("burial_latitude and burial_longitude must be given together")
        return self

    @model_validator(mode="after")
    def _check_partial_dates(self) -> "_ProfileFields":
        year_of = {"birth": getattr(self, "birth_year", None), "death": getattr(self, "death_year", None)}
        for prefix in ("birth", "death"):
            _check_partial_date(
                prefix,
                year_of[prefix],
                getattr(self, f"{prefix}_month"),
                getattr(self, f"{prefix}_day"),
                getattr(self, f"{prefix}_is_lunar"),
                getattr(self, f"{prefix}_leap_month"),
            )
        # Same year, both dates in the same calendar: the death cannot come before the birth.
        if (
            year_of["birth"] is not None
            and year_of["birth"] == year_of["death"]
            and self.birth_is_lunar == self.death_is_lunar
            and self.birth_month is not None
            and self.death_month is not None
            and (self.death_month, self.death_day or 0) < (self.birth_month, self.birth_day or 0)
        ):
            raise ValueError("death cannot be before birth")
        return self


class MemberCreate(_ProfileFields):
    full_name: str = Field(min_length=1)
    parent_id: int | None = None
    birth_year: int | None = None
    death_year: int | None = None
    gender: Gender | None = None
    notes: str | None = None

    @model_validator(mode="after")
    def _check_years(self) -> "MemberCreate":
        if (
            self.birth_year is not None
            and self.death_year is not None
            and self.death_year < self.birth_year
        ):
            raise ValueError("death_year cannot be before birth_year")
        return self


class MemberUpdate(_ProfileFields):
    full_name: str = Field(min_length=1)
    parent_id: int | None = None
    birth_year: int | None = None
    death_year: int | None = None
    gender: Gender | None = None
    notes: str | None = None

    @model_validator(mode="after")
    def _check_years(self) -> "MemberUpdate":
        if (
            self.birth_year is not None
            and self.death_year is not None
            and self.death_year < self.birth_year
        ):
            raise ValueError("death_year cannot be before birth_year")
        return self


class MarriageCreate(BaseModel):
    spouse_full_name: str = Field(min_length=1)
    spouse_birth_year: int | None = None
    spouse_death_year: int | None = None
    spouse_gender: Gender | None = None
    spouse_notes: str | None = None
    marriage_year: int | None = None

    @model_validator(mode="after")
    def _check_years(self) -> "MarriageCreate":
        if (
            self.spouse_birth_year is not None
            and self.spouse_death_year is not None
            and self.spouse_death_year < self.spouse_birth_year
        ):
            raise ValueError("spouse_death_year cannot be before spouse_birth_year")
        return self


class MarriageUpdate(BaseModel):
    spouse_full_name: str = Field(min_length=1)
    spouse_birth_year: int | None = None
    spouse_death_year: int | None = None
    spouse_gender: Gender | None = None
    spouse_notes: str | None = None
    marriage_year: int | None = None

    @model_validator(mode="after")
    def _check_years(self) -> "MarriageUpdate":
        if (
            self.spouse_birth_year is not None
            and self.spouse_death_year is not None
            and self.spouse_death_year < self.spouse_birth_year
        ):
            raise ValueError("spouse_death_year cannot be before spouse_birth_year")
        return self


class SpouseInfo(BaseModel):
    marriage_id: int
    marriage_year: int | None = None
    id: int
    full_name: str
    birth_year: int | None = None
    death_year: int | None = None
    gender: Gender | None = None
    notes: str | None = None


class MemberRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    full_name: str
    parent_id: int | None
    birth_year: int | None
    death_year: int | None
    gender: Gender | None
    notes: str | None
    avatar_url: str | None
    courtesy_name: str | None
    title: str | None
    residence: str | None
    burial_place: str | None
    burial_latitude: float | None
    burial_longitude: float | None
    hometown: str | None = None
    phone: str | None = None
    email: str | None = None
    birth_month: int | None = None
    birth_day: int | None = None
    death_month: int | None = None
    death_day: int | None = None
    birth_is_lunar: bool = False
    birth_leap_month: bool = False
    death_is_lunar: bool = True
    death_leap_month: bool = False
    birth_order: int | None = None
    is_adopted: bool = False
    mother_id: int | None = None
    created_at: datetime


class MemberTreeNode(BaseModel):
    id: int
    name: str
    birth_year: int | None = None
    death_year: int | None = None
    gender: Gender | None = None
    notes: str | None = None
    avatar_url: str | None = None
    spouses: list[SpouseInfo] = []
    children: list["MemberTreeNode"] = []


class MemberSkeletonNode(BaseModel):
    id: int
    name: str
    children: list["MemberSkeletonNode"] = []


class MemberDetail(BaseModel):
    id: int
    birth_year: int | None = None
    death_year: int | None = None
    gender: Gender | None = None
    notes: str | None = None
    avatar_url: str | None = None
    courtesy_name: str | None = None
    title: str | None = None
    residence: str | None = None
    burial_place: str | None = None
    burial_latitude: float | None = None
    burial_longitude: float | None = None
    sibling_rank: str | None = None
    hometown: str | None = None
    phone: str | None = None
    email: str | None = None
    birth_month: int | None = None
    birth_day: int | None = None
    death_month: int | None = None
    death_day: int | None = None
    birth_is_lunar: bool = False
    birth_leap_month: bool = False
    death_is_lunar: bool = True
    death_leap_month: bool = False
    birth_order: int | None = None
    is_adopted: bool = False
    mother_id: int | None = None
    spouses: list[SpouseInfo] = []
