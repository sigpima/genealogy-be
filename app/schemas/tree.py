from datetime import datetime

from typing import Literal

from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator

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
    status: str = "active"
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


class TreeDelete(BaseModel):
    """Deleting a family means typing its slug again."""

    slug: str


class TreeAdminRead(TreeAdmin):
    last_login_at: datetime | None = None


class AdminAdd(BaseModel):
    """Either a brand-new admin (`email` + `full_name`, password optional) or `user_id` of one of the family's own users to promote."""

    user_id: int | None = None
    email: EmailStr | None = None
    full_name: str | None = Field(default=None, min_length=1)
    password: str | None = Field(default=None, min_length=8)

    @model_validator(mode="after")
    def _one_way_or_the_other(self) -> "AdminAdd":
        creating = self.email is not None or self.full_name is not None
        if (self.user_id is None) == (not creating):
            raise ValueError("give either user_id or email + full_name")
        if creating and (self.email is None or self.full_name is None):
            raise ValueError("a new admin needs email and full_name")
        return self


class TreeAdminCreated(BaseModel):
    admin: TreeAdminRead
    password: str | None = None


class AdminStatusIn(BaseModel):
    status: Literal["active", "disabled"]


class PasswordIn(BaseModel):
    password: str | None = Field(default=None, min_length=8)


class PasswordOut(BaseModel):
    password: str
