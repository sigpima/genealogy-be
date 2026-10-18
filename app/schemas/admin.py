from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.schemas.calendar import Subscription
from app.schemas.search import PersonRef
from app.schemas.user import UserRead

Role = Literal["admin", "member"]
Status = Literal["pending", "active", "disabled"]


class AdminUserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    full_name: str = Field(min_length=1)
    role: Role = "member"


class AdminUserUpdate(BaseModel):
    """Only the fields present change; `member_id: null` explicitly unlinks the person."""

    role: Role | None = None
    status: Status | None = None
    member_id: int | None = None


class AdminUserRead(UserRead):
    last_login_at: datetime | None = None
    member: PersonRef | None = None


class PasswordReset(BaseModel):
    password: str | None = Field(default=None, min_length=8)


class PasswordResetResult(BaseModel):
    password: str


class SiteInfo(BaseModel):
    """What the public login page may know about the tree a visitor refers to."""

    visibility: Literal["private", "public"]
    tree_name: str | None = None
    tree_slug: str | None = None


class SiteSettingsPayload(BaseModel):
    visibility: Literal["private", "public"]


PrivacyLevel = Literal["admin", "member", "public"]


class PrivacyPayload(BaseModel):
    """Levels to change (the others stay as they are). Unknown fields are refused."""

    model_config = ConfigDict(extra="forbid")

    phone: PrivacyLevel | None = None
    email: PrivacyLevel | None = None
    residence: PrivacyLevel | None = None
    notes: PrivacyLevel | None = None
    burial: PrivacyLevel | None = None
    avatar: PrivacyLevel | None = None
    hometown: PrivacyLevel | None = None


class PrivacyRead(BaseModel):
    fields: dict[str, PrivacyLevel]


class Shares(BaseModel):
    calendar: Subscription
    open_cards: int
