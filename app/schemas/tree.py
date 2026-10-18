from datetime import datetime

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.core.tenants import SLUG_PATTERN


def _clean_name(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("name must not be empty")
    return value


def _check_slug(value: str) -> str:
    if len(value) > 60 or not SLUG_PATTERN.match(value):
        raise ValueError("slug must be lowercase letters/digits separated by single hyphens (max 60)")
    return value


class TreeAdmin(BaseModel):
    id: int
    email: EmailStr
    full_name: str
    status: str


class TreeRead(BaseModel):
    id: int
    name: str
    slug: str
    created_at: datetime
    member_count: int = 0
    user_count: int = 0
    admins: list[TreeAdmin] = []
    #: Latest of the family's audit-log entries and its users' last logins; null when nothing has happened yet.
    last_activity: datetime | None = None
    #: The tree this request acts on (the superadmin's current choice).
    is_current: bool = False


class TreeCreate(BaseModel):
    name: str = Field(max_length=255)
    slug: str
    admin_email: EmailStr
    admin_name: str = Field(min_length=1)
    #: Omit to have one generated (it is returned once, in the response).
    admin_password: str | None = Field(default=None, min_length=8)

    _name = field_validator("name")(_clean_name)
    _slug = field_validator("slug")(_check_slug)


class TreeUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=255)
    slug: str | None = None

    @field_validator("name")
    @classmethod
    def _name(cls, value: str | None) -> str | None:
        return None if value is None else _clean_name(value)

    @field_validator("slug")
    @classmethod
    def _slug(cls, value: str | None) -> str | None:
        return None if value is None else _check_slug(value)


class TreeCreated(BaseModel):
    tree: TreeRead
    admin: TreeAdmin
    admin_password: str | None = None
