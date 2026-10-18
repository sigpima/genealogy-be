from datetime import datetime
from typing import Literal

from app.core.map_links import clean_map_url, coordinates_from
from pydantic import BaseModel, Field, field_validator, model_validator

PLACE_KINDS = ("clan_house", "temple", "tomb", "cemetery", "other")


class PlaceRef(BaseModel):
    """A place as shown on a person's profile."""

    id: int
    name: str
    kind: str
    latitude: float | None = None
    longitude: float | None = None


class PlaceBase(BaseModel):
    kind: Literal["clan_house", "temple", "tomb", "cemetery", "other"]
    name: str = Field(max_length=150)
    address: str | None = Field(default=None, max_length=500)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    map_url: str | None = Field(default=None, max_length=500)  # a Google Maps link
    description: str | None = Field(default=None, max_length=5000)
    caretaker: str | None = Field(default=None, max_length=255)
    visit_notes: str | None = Field(default=None, max_length=5000)

    @field_validator("name")
    @classmethod
    def _name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("name must not be empty")
        return value

    @field_validator("address", "description", "caretaker", "visit_notes", mode="before")
    @classmethod
    def _blank_to_none(cls, value: object) -> object:
        if isinstance(value, str):
            value = value.strip()
            return value or None
        return value

    @field_validator("map_url", mode="before")
    @classmethod
    def _check_map_url(cls, value: object) -> object:
        return clean_map_url(value) if isinstance(value, str) or value is None else value

    @model_validator(mode="after")
    def _position_from_link(self) -> "PlaceBase":
        found = coordinates_from(self.map_url) if self.map_url else None
        if found is not None:
            self.latitude, self.longitude = found
        return self

    @model_validator(mode="after")
    def _gps_pair(self) -> "PlaceBase":
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("latitude and longitude must be given together")
        return self


class PlaceCreate(PlaceBase):
    pass


class PlaceUpdate(PlaceBase):
    """PUT replaces the place: an omitted field is cleared."""


class PlaceRead(PlaceBase):
    id: int
    resting_count: int = 0
    media_count: int = 0
    created_at: datetime


class Resident(BaseModel):
    id: int
    full_name: str
    plot: str | None
    birth_year: int | None
    death_year: int | None


class PlaceDetail(PlaceRead):
    residents: list[Resident] = []


class MigrationGroup(BaseModel):
    name: str
    count: int
    latitude: float | None
    longitude: float | None
    #: A place with this name already exists and would be reused.
    existing: bool


class MigrationResult(BaseModel):
    dry_run: bool
    groups: list[MigrationGroup]
    created: int
    linked: int
