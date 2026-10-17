from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Gender(str, Enum):
    male = "male"
    female = "female"
    other = "other"


class _ProfileFields(BaseModel):
    """Profile fields shared by create and update: stripped, blank -> None, GPS both-or-neither."""

    courtesy_name: str | None = Field(default=None, max_length=100)
    title: str | None = Field(default=None, max_length=150)
    residence: str | None = Field(default=None, max_length=255)
    burial_place: str | None = Field(default=None, max_length=500)
    burial_latitude: float | None = Field(default=None, ge=-90, le=90)
    burial_longitude: float | None = Field(default=None, ge=-180, le=180)

    @field_validator("courtesy_name", "title", "residence", "burial_place", mode="before")
    @classmethod
    def _blank_to_none(cls, value: object) -> object:
        if isinstance(value, str):
            value = value.strip()
            return value or None
        return value

    @model_validator(mode="after")
    def _check_gps(self) -> "_ProfileFields":
        if (self.burial_latitude is None) != (self.burial_longitude is None):
            raise ValueError("burial_latitude and burial_longitude must be given together")
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
    spouses: list[SpouseInfo] = []
