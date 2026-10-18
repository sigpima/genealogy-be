"""Privacy per field (see the GĐ11 design): one place that decides who may see which sensitive member field.

Levels: `admin` (admins only), `member` (any signed-in member of the tree), `public` (also guests of a public tree).
Stored as `site_settings` rows `privacy.<field>`; a missing row means the default, which keeps the pre-GĐ11 behaviour.
"""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.roles import ADMIN_ROLES
from app.models.site_setting import SiteSetting
from app.models.user import User

LEVELS = ("admin", "member", "public")
RANK = {"public": 0, "member": 1, "admin": 2}
DEFAULTS: dict[str, str] = {
    "phone": "member",
    "email": "member",
    "residence": "member",
    "notes": "member",
    "burial": "member",
    "avatar": "public",
    "hometown": "public",
}
#: member columns that belong to each configurable field (what a change request may name)
COLUMNS: dict[str, tuple[str, ...]] = {
    "phone": ("phone",),
    "email": ("email",),
    "residence": ("residence",),
    "notes": ("notes",),
    "burial": ("burial_place", "burial_latitude", "burial_longitude", "burial_place_id", "burial_plot", "burial_map_url"),
    "avatar": ("avatar_url",),
    "hometown": ("hometown",),
}
FIELD_OF_COLUMN = {column: field for field, columns in COLUMNS.items() for column in columns}
KEY_PREFIX = "privacy."


def viewer_rank(user: User | None) -> int:
    """guest 0, signed-in member 1, admin/superadmin 2."""
    if user is None:
        return RANK["public"]
    return RANK["admin"] if user.role in ADMIN_ROLES else RANK["member"]


@dataclass(frozen=True)
class Privacy:
    levels: dict[str, str]
    rank: int

    def can_see(self, field: str) -> bool:
        return self.rank >= RANK[self.levels[field]]

    def can_see_everything(self) -> bool:
        return self.rank >= RANK["admin"]

    def hides_column(self, column: str) -> bool:
        field = FIELD_OF_COLUMN.get(column)
        return field is not None and not self.can_see(field)


async def field_levels(db: AsyncSession, tree_id: int) -> dict[str, str]:
    rows = await db.execute(select(SiteSetting).where(SiteSetting.tree_id == tree_id, SiteSetting.key.like(f"{KEY_PREFIX}%")))
    stored = {row.key[len(KEY_PREFIX) :]: row.value for row in rows.scalars()}
    return {field: (stored[field] if stored.get(field) in LEVELS else default) for field, default in DEFAULTS.items()}


async def privacy_for(db: AsyncSession, tree_id: int, user: User | None) -> Privacy:
    return Privacy(await field_levels(db, tree_id), viewer_rank(user))
