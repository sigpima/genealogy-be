from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.core.permissions import get_write_context
from app.core.privacy import KEY_PREFIX, field_levels
from app.core.roles import ROLE_ADMIN, STATUS_ACTIVE, get_tree_settings
from app.core.security import hash_password
from app.core.tenancy import TreeContext
from app.db.session import get_db
from app.models.site_setting import SiteSetting
from app.models.user import User
from app.schemas.admin import AdminUserCreate, AdminUserUpdate, PrivacyPayload, PrivacyRead, SiteSettingsPayload
from app.schemas.user import UserRead

# Everything here acts on ONE tree: the admin's own, or the one a superadmin picked (X-Tree-Id).
router = APIRouter(prefix="/admin", tags=["admin"])


def _read(user: User, ctx: TreeContext) -> UserRead:
    read = UserRead.model_validate(user)
    read.tree_name = ctx.tree.name if user.tree_id == ctx.tree.id else None
    return read


async def _user_in_tree(db: AsyncSession, ctx: TreeContext, user_id: int) -> User | None:
    user = await db.get(User, user_id)
    # Superadmins have no tree, so a tree admin can neither see nor modify them (404, never 403).
    return user if user is not None and user.tree_id == ctx.tree.id else None


@router.get("/users", response_model=list[UserRead])
async def list_users(
    ctx: TreeContext = Depends(get_write_context), db: AsyncSession = Depends(get_db)
) -> list[UserRead]:
    rows = await db.execute(select(User).where(User.tree_id == ctx.tree.id).order_by(User.id))
    return [_read(user, ctx) for user in rows.scalars().all()]


@router.post("/users", response_model=UserRead, status_code=status.HTTP_201_CREATED)
async def create_user(
    payload: AdminUserCreate,
    ctx: TreeContext = Depends(get_write_context),
    db: AsyncSession = Depends(get_db),
) -> UserRead:
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
    await db.commit()
    await db.refresh(user)
    return _read(user, ctx)


@router.patch("/users/{user_id}", response_model=UserRead)
async def update_user(
    user_id: int,
    payload: AdminUserUpdate,
    ctx: TreeContext = Depends(get_write_context),
    db: AsyncSession = Depends(get_db),
) -> UserRead:
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

    user.role = new_role
    user.status = new_status
    await db.commit()
    await db.refresh(user)
    return _read(user, ctx)


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
    for key, value in payload.model_dump().items():
        row = await db.get(SiteSetting, (ctx.tree.id, key))
        if row is None:
            db.add(SiteSetting(tree_id=ctx.tree.id, key=key, value=value))
        else:
            row.value = value
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
