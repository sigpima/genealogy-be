"""The admin's "Cần làm" list: what is waiting for this tree's admin right now (see the admin console design).

Items with nothing to do are left out; notices (standing conditions worth knowing) come after the tasks.
"""

import datetime

from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import calendar_items
from app.core.backup_status import read_backup_status
from app.core.config import get_settings
from app.core.data_health import check_layout, check_media
from app.core.tree_layout import load_layout
from app.models.audit_log import AuditLog
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
    since = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=24)
    locked = await _count(
        db, AuditLog.tree_id == tree.id, AuditLog.action == "security.locked", AuditLog.created_at >= since, model=AuditLog
    )
    issues = [
        f
        for f in [*check_layout(await load_layout(db, tree.id)), *await check_media(db, tree.id, Path(get_settings().upload_dir))]
        if f.severity == "warning"
    ]
    backup = read_backup_status(Path(get_settings().backup_dir), datetime.datetime.now(calendar_items.VN_TIMEZONE))
    tasks: list[TodoItem] = []
    if pending_users:
        tasks.append(TodoItem(key="pending_users", count=pending_users, text=f"{pending_users} người đăng ký đang chờ duyệt", href="/admin/nguoi-dung?trang-thai=pending", kind="task"))
    if pending_requests:
        tasks.append(TodoItem(key="pending_requests", count=pending_requests, text=f"{pending_requests} yêu cầu chỉnh sửa chờ duyệt", href="/yeu-cau", kind="task"))
    if backup.state != "ok":
        text = "Chưa có bản sao lưu nào được ghi nhận" if backup.state == "never" else f"Bản sao lưu gần nhất đã {backup.age_days} ngày trước"
        tasks.append(TodoItem(key="backup_old", count=1, text=text, href="/admin/sao-luu", kind="task"))
    if issues:
        tasks.append(TodoItem(key="data_issues", count=len(issues), text=f"{len(issues)} chỗ dữ liệu có vẻ sai hoặc vô lý", href="/admin/suc-khoe-du-lieu", kind="task"))
    if locked:
        tasks.append(TodoItem(key="locked_accounts", count=locked, text=f"{locked} lần tài khoản bị khoá tạm vì đăng nhập sai trong 24 giờ qua", href="/admin/nhat-ky?loai=security", kind="task"))
    notices: list[TodoItem] = []
    if settings["visibility"] == "public":
        notices.append(TodoItem(key="public_tree", count=1, text="Cây đang công khai: ai cũng xem được", href="/admin/cai-dat", kind="notice"))
    if settings["registration"] == "open":
        notices.append(TodoItem(key="open_registration", count=1, text="Đăng ký đang mở: ai cũng tự đăng ký được", href="/admin/cai-dat", kind="notice"))
    return Overview(
        items=[*tasks, *notices],
        counts={"members": members, "users": users, "pending_users": pending_users, "pending_requests": pending_requests},
    )
