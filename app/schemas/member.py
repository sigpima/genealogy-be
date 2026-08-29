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


class MemberRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    full_name: str
    parent_id: int | None
    birth_year: int | None
    death_year: int | None
    gender: Gender | None
    notes: str | None
    created_at: datetime


class MemberTreeNode(BaseModel):
    id: int
    name: str
    birth_year: int | None = None
    death_year: int | None = None
    gender: Gender | None = None
    notes: str | None = None
    children: list["MemberTreeNode"] = []
