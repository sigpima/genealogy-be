from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

KINDS = ("edit", "add_child", "report")
STATUSES = ("pending", "approved", "rejected", "cancelled")


class RequestCreate(BaseModel):
    kind: Literal["edit", "add_child", "report"]
    member_id: int
    #: Proposed field values (edit / add_child); empty for a report.
    changes: dict[str, Any] = Field(default_factory=dict)
    message: str | None = Field(default=None, max_length=2000)

    @field_validator("message")
    @classmethod
    def _message(cls, value: str | None) -> str | None:
        value = (value or "").strip()
        return value or None


class Decision(BaseModel):
    note: str | None = Field(default=None, max_length=2000)

    @field_validator("note")
    @classmethod
    def _note(cls, value: str | None) -> str | None:
        value = (value or "").strip()
        return value or None


class PersonName(BaseModel):
    id: int | None
    name: str


class DiffRow(BaseModel):
    field: str
    old: Any
    new: Any
    #: Pending only: the person's current value no longer equals what it was when the request was sent.
    stale: bool = False


class RequestRead(BaseModel):
    id: int
    kind: str
    status: str
    member_id: int | None
    member_name: str | None
    message: str | None
    changes: dict[str, Any]
    base: dict[str, Any]
    diff: list[DiffRow]
    stale: bool
    requester: PersonName
    reviewer: PersonName | None
    review_note: str | None
    result_member_id: int | None
    created_at: datetime
    reviewed_at: datetime | None


class RequestPage(BaseModel):
    total: int
    items: list[RequestRead]


class RequestSummary(BaseModel):
    pending: int
