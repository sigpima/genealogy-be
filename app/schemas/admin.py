from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field

Role = Literal["admin", "member"]
Status = Literal["pending", "active", "disabled"]


class AdminUserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    full_name: str = Field(min_length=1)
    role: Role = "member"


class AdminUserUpdate(BaseModel):
    role: Role | None = None
    status: Status | None = None


class SiteInfo(BaseModel):
    """What the public login/signup pages may know about the tree a visitor refers to."""

    visibility: Literal["private", "public"]
    registration: Literal["open", "approval", "closed"]
    tree_name: str | None = None
    tree_slug: str | None = None


class SiteSettingsPayload(BaseModel):
    visibility: Literal["private", "public"]
    registration: Literal["open", "approval", "closed"]


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
