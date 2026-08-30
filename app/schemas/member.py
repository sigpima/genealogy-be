from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Gender(str, Enum):
    male = "male"
    female = "female"
    other = "other"


class MemberCreate(BaseModel):
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


class MemberUpdate(BaseModel):
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
    spouses: list[SpouseInfo] = []
