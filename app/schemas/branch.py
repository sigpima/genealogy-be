import re

from pydantic import BaseModel, Field, field_validator

COLOR_PATTERN = re.compile(r"^#[0-9a-fA-F]{6}$")


class BranchBase(BaseModel):
    name: str = Field(max_length=150)
    root_member_id: int
    color: str | None = None
    description: str | None = None

    @field_validator("name")
    @classmethod
    def _name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("name must not be empty")
        return value

    @field_validator("color")
    @classmethod
    def _color(cls, value: str | None) -> str | None:
        if value is None or value == "":
            return None
        if not COLOR_PATTERN.match(value):
            raise ValueError("color must look like #rrggbb")
        return value.lower()

    @field_validator("description")
    @classmethod
    def _description(cls, value: str | None) -> str | None:
        value = (value or "").strip()
        return value or None


class BranchCreate(BranchBase):
    pass


class BranchUpdate(BranchBase):
    """PUT replaces the branch: an omitted description is cleared (an omitted colour keeps the current one)."""


class BranchRead(BaseModel):
    id: int
    name: str
    color: str
    description: str | None
    root_member_id: int
    root_name: str
    root_generation: int
    member_count: int


class BranchRef(BaseModel):
    """A member's branch as shown on their profile and in search results."""

    id: int
    name: str
    color: str
