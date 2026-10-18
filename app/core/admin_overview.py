"""The admin's "Cần làm" list: what is waiting for this tree's admin right now (see the admin console design).

Items with nothing to do are left out; notices (standing conditions worth knowing) come after the tasks.
"""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.change_request import ChangeRequest
from app.models.member import Member
from app.models.tree import Tree
from app.models.user import User
from app.schemas.admin_overview import Overview, TodoItem


async def _count(db: AsyncSession, *conditions, model) -> int:
    return (await db.execute(select(func.count()).select_from(model).where(*conditions))).scalar_one()


async def compute_overview(db: AsyncSession, tree: Tree, settings: dict[str, str]) -> Overview:
    members = await _count(db, Member.tree_id == tree.id, model=Member)
    users = await _count(db, User.tree_id == tree.id, model=User)
    pending_users = await _count(db, User.tree_id == tree.id, User.status == "pending", model=User)
    pending_requests = await _count(
        db, ChangeRequest.tree_id == tree.id, ChangeRequest.status == "pending", model=ChangeRequest
    )
    tasks: list[TodoItem] = []
    if pending_users:
        tasks.append(TodoItem(key="pending_users", count=pending_users, text=f"{pending_users} người đăng ký đang chờ duyệt", href="/admin/nguoi-dung?trang-thai=pending", kind="task"))
    if pending_requests:
        tasks.append(TodoItem(key="pending_requests", count=pending_requests, text=f"{pending_requests} yêu cầu chỉnh sửa chờ duyệt", href="/yeu-cau", kind="task"))
    notices: list[TodoItem] = []
    if settings["visibility"] == "public":
        notices.append(TodoItem(key="public_tree", count=1, text="Cây đang công khai: ai cũng xem được", href="/admin/cai-dat", kind="notice"))
    if settings["registration"] == "open":
        notices.append(TodoItem(key="open_registration", count=1, text="Đăng ký đang mở: ai cũng tự đăng ký được", href="/admin/cai-dat", kind="notice"))
    return Overview(
        items=[*tasks, *notices],
        counts={"members": members, "users": users, "pending_users": pending_users, "pending_requests": pending_requests},
    )
