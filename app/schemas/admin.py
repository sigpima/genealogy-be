from typing import Literal

from pydantic import BaseModel, EmailStr, Field

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


class SiteSettingsPayload(BaseModel):
    visibility: Literal["private", "public"]
    registration: Literal["open", "approval", "closed"]
