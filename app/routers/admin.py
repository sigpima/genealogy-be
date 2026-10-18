import datetime
import secrets
from dataclasses import asdict
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit, calendar_items
from app.core.admin_overview import compute_overview
from app.core.backup_status import BackupStatus, read_backup_status
from app.core.config import get_settings
from app.core.data_health import check_layout, check_media
from app.core.permissions import get_write_context
from app.core.privacy import KEY_PREFIX, field_levels
from app.core.roles import ROLE_ADMIN, STATUS_ACTIVE, STATUS_PENDING, get_tree_settings
from app.core.security import hash_password
from app.core.tenancy import TreeContext
from app.core.text import fold
from app.core.tree_layout import load_layout
from app.db.session import get_db
from app.models.event_card import EventCard
from app.models.member import Member
from app.models.site_setting import SiteSetting
from app.models.user import User
from app.schemas.admin_overview import Overview
from app.schemas.data_health import DataHealth, FindingRead
from app.schemas.admin import (
    AdminUserCreate,
    AdminUserRead,
    AdminUserUpdate,
    BulkApproved,
    BulkApprove,
    PasswordReset,
    PasswordResetResult,
    PrivacyPayload,
    PrivacyRead,
    Shares,
    SiteSettingsPayload,
)
from app.routers.calendar import _subscription
from app.schemas.search import PersonRef

# Everything here acts on ONE tree: the admin's own, or the one a superadmin picked (X-Tree-Id).
router = APIRouter(prefix="/admin", tags=["admin"])


async def _reads(db: AsyncSession, users: list[User], ctx: TreeContext) -> list[AdminUserRead]:
    """Users with their tree name and the person they are linked to (one query for all the people)."""
    linked = {u.member_id for u in users if u.member_id is not None}
    names = (
        dict((await db.execute(select(Member.id, Member.full_name).where(Member.id.in_(linked)))).all()) if linked else {}
    )
    reads = []
    for user in users:
        read = AdminUserRead.model_validate(user)
        read.tree_name = ctx.tree.name if user.tree_id == ctx.tree.id else None
        if user.member_id in names:
            read.member = PersonRef(id=user.member_id, name=names[user.member_id])
        reads.append(read)
    return reads


async def _user_in_tree(db: AsyncSession, ctx: TreeContext, user_id: int) -> User | None:
    user = await db.get(User, user_id)
    # Superadmins have no tree, so a tree admin can neither see nor modify them (404, never 403).
    return user if user is not None and user.tree_id == ctx.tree.id else None


@router.get("/users", response_model=list[AdminUserRead])
async def list_users(
    q: str | None = None,
    status_: Literal["pending", "active", "disabled"] | None = Query(default=None, alias="status"),
    role: Literal["admin", "member"] | None = None,
    ctx: TreeContext = Depends(get_write_context),
    db: AsyncSession = Depends(get_db),
) -> list[AdminUserRead]:
    conditions = [User.tree_id == ctx.tree.id]
    if status_ is not None:
        conditions.append(User.status == status_)
    if role is not None:
        conditions.append(User.role == role)
    rows = list((await db.execute(select(User).where(*conditions).order_by(User.id))).scalars().all())
    if q and q.strip():
        needle = fold(q)
        rows = [u for u in rows if needle in fold(u.full_name) or needle in fold(u.email)]
    return await _reads(db, rows, ctx)


@router.post("/users", response_model=AdminUserRead, status_code=status.HTTP_201_CREATED)
async def create_user(
    payload: AdminUserCreate,
    ctx: TreeContext = Depends(get_write_context),
    db: AsyncSession = Depends(get_db),
) -> AdminUserRead:
    existing = await db.execute(select(User).where(User.email == payload.email))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="email already registered")
    user = User(
        email=payload.email,
        hashed_password=hash_password(payload.password),
        full_name=payload.full_name,
        role=payload.role,
        status=STATUS_ACTIVE,  # created by an admin, so no approval step
        tree_id=ctx.tree.id,
    )
    db.add(user)
    audit.record(db, tree_id=ctx.tree.id, actor=ctx.user, action="user.create", details={"email": payload.email, "role": payload.role})
    await db.commit()
    await db.refresh(user)
    return (await _reads(db, [user], ctx))[0]


@router.post("/users/approve", response_model=BulkApproved)
async def approve_users(
    payload: BulkApprove, ctx: TreeContext = Depends(get_write_context), db: AsyncSession = Depends(get_db)
) -> BulkApproved:
    """Approve every pending user of this tree among `ids`; any other id (active, another tree, unknown) is ignored."""
    rows = (
        await db.execute(
            select(User).where(User.id.in_(payload.ids), User.tree_id == ctx.tree.id, User.status == STATUS_PENDING).order_by(User.id)
        )
    ).scalars().all()
    for user in rows:
        user.status = STATUS_ACTIVE
        audit.record(db, tree_id=ctx.tree.id, actor=ctx.user, action="user.approve", details={"email": user.email})
    await db.commit()
    return BulkApproved(approved=[u.id for u in rows])


@router.post("/users/{user_id}/password", response_model=PasswordResetResult)
async def reset_password(
    user_id: int,
    payload: PasswordReset,
    ctx: TreeContext = Depends(get_write_context),
    db: AsyncSession = Depends(get_db),
) -> PasswordResetResult:
    """Set a new password for one of this tree's users and return it ONCE (it is never stored in clear or audited)."""
    user = await _user_in_tree(db, ctx, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="user not found")
    password = payload.password or secrets.token_urlsafe(9)
    user.hashed_password = hash_password(password)
    audit.record(db, tree_id=ctx.tree.id, actor=ctx.user, action="user.password_reset", details={"email": user.email})
    await db.commit()
    return PasswordResetResult(password=password)


@router.patch("/users/{user_id}", response_model=AdminUserRead)
async def update_user(
    user_id: int,
    payload: AdminUserUpdate,
    ctx: TreeContext = Depends(get_write_context),
    db: AsyncSession = Depends(get_db),
) -> AdminUserRead:
    user = await _user_in_tree(db, ctx, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="user not found")

    new_role = payload.role or user.role
    new_status = payload.status or user.status

    was_active_admin = user.role == ROLE_ADMIN and user.status == STATUS_ACTIVE
    stays_active_admin = new_role == ROLE_ADMIN and new_status == STATUS_ACTIVE
    if was_active_admin and not stays_active_admin:
        other_admins = (
            await db.execute(
                select(func.count())
                .select_from(User)
                .where(
                    User.tree_id == ctx.tree.id,
                    User.role == ROLE_ADMIN,
                    User.status == STATUS_ACTIVE,
                    User.id != user.id,
                )
            )
        ).scalar_one()
        if other_admins == 0:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="there must always be at least one active admin",
            )

    before = {"role": user.role, "status": user.status, "member_id": user.member_id}
    after = {"role": new_role, "status": new_status, "member_id": user.member_id}
    if "member_id" in payload.model_fields_set:
        if payload.member_id is not None:
            person = await db.get(Member, payload.member_id)
            if person is None or person.tree_id != ctx.tree.id:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="member not found")
            taken = (
                await db.execute(select(User.id).where(User.member_id == payload.member_id, User.id != user.id))
            ).scalar_one_or_none()
            if taken is not None:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="that person is already linked to another account")
        after["member_id"] = payload.member_id

    user.role, user.status, user.member_id = new_role, new_status, after["member_id"]
    changes = audit.diff_values(before, after)
    if changes:
        audit.record(
            db, tree_id=ctx.tree.id, actor=ctx.user, action="user.update", changes=changes, details={"email": user.email}
        )
    await db.commit()
    await db.refresh(user)
    return (await _reads(db, [user], ctx))[0]


@router.get("/settings", response_model=SiteSettingsPayload)
async def read_settings(
    ctx: TreeContext = Depends(get_write_context), db: AsyncSession = Depends(get_db)
) -> dict[str, str]:
    return await get_tree_settings(db, ctx.tree.id)


@router.put("/settings", response_model=SiteSettingsPayload)
async def update_settings(
    payload: SiteSettingsPayload,
    ctx: TreeContext = Depends(get_write_context),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    before = await get_tree_settings(db, ctx.tree.id)
    for key, value in payload.model_dump().items():
        row = await db.get(SiteSetting, (ctx.tree.id, key))
        if row is None:
            db.add(SiteSetting(tree_id=ctx.tree.id, key=key, value=value))
        else:
            row.value = value
    changes = audit.diff_values(before, payload.model_dump())
    if changes:
        audit.record(db, tree_id=ctx.tree.id, actor=ctx.user, action="settings.update", changes=changes)
    await db.commit()
    return await get_tree_settings(db, ctx.tree.id)


@router.get("/privacy", response_model=PrivacyRead)
async def read_privacy(ctx: TreeContext = Depends(get_write_context), db: AsyncSession = Depends(get_db)) -> PrivacyRead:
    return PrivacyRead(fields=await field_levels(db, ctx.tree.id))


@router.put("/privacy", response_model=PrivacyRead)
async def update_privacy(
    payload: PrivacyPayload, ctx: TreeContext = Depends(get_write_context), db: AsyncSession = Depends(get_db)
) -> PrivacyRead:
    """Who may see which sensitive field; only the fields present in the payload change."""
    before = await field_levels(db, ctx.tree.id)
    wanted = {name: level for name, level in payload.model_dump().items() if level is not None}
    for name, level in wanted.items():
        key = KEY_PREFIX + name
        row = await db.get(SiteSetting, (ctx.tree.id, key))
        if row is None:
            db.add(SiteSetting(tree_id=ctx.tree.id, key=key, value=level))
        else:
            row.value = level
    after = {**before, **wanted}
    changes = audit.diff_values(before, after)
    if changes:
        audit.record(db, tree_id=ctx.tree.id, actor=ctx.user, action="privacy.update", changes=changes)
    await db.commit()
    return PrivacyRead(fields=await field_levels(db, ctx.tree.id))


@router.get("/overview", response_model=Overview)
async def overview(ctx: TreeContext = Depends(get_write_context), db: AsyncSession = Depends(get_db)) -> Overview:
    """What is waiting for this tree's admin (the "Cần làm" box of the admin home)."""
    return await compute_overview(db, ctx.tree, await get_tree_settings(db, ctx.tree.id))


@router.get("/shares", response_model=Shares)
async def shares(ctx: TreeContext = Depends(get_write_context), db: AsyncSession = Depends(get_db)) -> Shares:
    """The links this tree has handed out: the calendar feed and the invitation cards that still take answers."""
    cards = (await db.execute(select(EventCard).where(EventCard.tree_id == ctx.tree.id, EventCard.closed.is_(False)))).scalars().all()
    open_cards = sum(1 for c in cards if c.closes_on is None or calendar_items.vn_today() <= c.closes_on)
    return Shares(calendar=_subscription(ctx.tree), open_cards=open_cards)


@router.get("/data-health", response_model=DataHealth)
async def data_health(ctx: TreeContext = Depends(get_write_context), db: AsyncSession = Depends(get_db)) -> DataHealth:
    """Probable typos in this tree's data: impossible or odd dates, likely duplicates, media files missing on disk."""
    found = [*check_layout(await load_layout(db, ctx.tree.id)), *await check_media(db, ctx.tree.id, Path(get_settings().upload_dir))]
    counts: dict[str, int] = {}
    for f in found:
        counts[f.kind] = counts.get(f.kind, 0) + 1
    return DataHealth(findings=[FindingRead(**asdict(f)) for f in found], counts=counts)


@router.get("/backup-status", response_model=BackupStatus)
async def backup_status(ctx: TreeContext = Depends(get_write_context)) -> BackupStatus:
    """When the last backup was made (status only; see app/core/backup_status.py for why there is nothing more)."""
    return read_backup_status(Path(get_settings().backup_dir), datetime.datetime.now(calendar_items.VN_TIMEZONE))
