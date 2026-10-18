"""The superadmin's "Cần làm" list and platform numbers (see the superadmin console design). Zero-count tasks are left out."""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.roles import ROLE_ADMIN, STATUS_ACTIVE
from app.models.media import Media
from app.models.member import Member
from app.models.tree import Tree
from app.models.user import User
from app.schemas.admin_overview import TodoItem
from app.schemas.platform import PlatformOverview


async def _scalar(db: AsyncSession, statement) -> int:
    return int((await db.execute(statement)).scalar_one() or 0)


async def compute_platform_overview(db: AsyncSession) -> PlatformOverview:
    trees = await _scalar(db, select(func.count()).select_from(Tree))
    members = await _scalar(db, select(func.count()).select_from(Member))
    users = await _scalar(db, select(func.count()).select_from(User).where(User.tree_id.is_not(None)))  # the families' accounts, not the platform owner
    media_bytes = await _scalar(db, select(func.coalesce(func.sum(Media.size), 0)))
    paused = await _scalar(db, select(func.count()).select_from(Tree).where(Tree.status == "paused"))
    with_admin = select(User.tree_id).where(User.role == ROLE_ADMIN, User.status == STATUS_ACTIVE).distinct()
    without_admin = await _scalar(db, select(func.count()).select_from(Tree).where(Tree.id.not_in(with_admin), Tree.status == "active"))
    tasks: list[TodoItem] = []
    if without_admin:
        tasks.append(
            TodoItem(
                key="trees_without_admin",
                count=without_admin,
                text=f"{without_admin} họ không có quản trị viên đang hoạt động",
                href="/he-thong/ho?loc=khong-admin",
                kind="task",
            )
        )
    if paused:
        tasks.append(TodoItem(key="trees_paused", count=paused, text=f"{paused} họ đang tạm ngưng", href="/he-thong/ho?loc=tam-ngung", kind="task"))
    return PlatformOverview(
        items=tasks,
        numbers={"trees": trees, "trees_paused": paused, "members": members, "users": users, "media_bytes": media_bytes},
    )
