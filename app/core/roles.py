"""Roles, account statuses and site settings: the allowed values and their defaults."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.site_setting import SiteSetting

ROLE_ADMIN = "admin"
ROLE_MEMBER = "member"
ROLES = (ROLE_ADMIN, ROLE_MEMBER)

STATUS_PENDING = "pending"
STATUS_ACTIVE = "active"
STATUS_DISABLED = "disabled"
STATUSES = (STATUS_PENDING, STATUS_ACTIVE, STATUS_DISABLED)

# key -> (allowed values, default). A missing row means the default.
SETTINGS: dict[str, tuple[tuple[str, ...], str]] = {
    "visibility": (("private", "public"), "private"),
    "registration": (("open", "approval", "closed"), "approval"),
}


async def get_site_settings(db: AsyncSession) -> dict[str, str]:
    stored = {row.key: row.value for row in (await db.execute(select(SiteSetting))).scalars()}
    resolved = {}
    for key, (allowed, default) in SETTINGS.items():
        value = stored.get(key, default)
        resolved[key] = value if value in allowed else default
    return resolved
