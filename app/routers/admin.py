from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import require_admin
from app.core.roles import ROLE_ADMIN, STATUS_ACTIVE, get_site_settings
from app.core.security import hash_password
from app.db.session import get_db
from app.models.site_setting import SiteSetting
from app.models.user import User
from app.schemas.admin import AdminUserCreate, AdminUserUpdate, SiteSettingsPayload
from app.schemas.user import UserRead

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])


@router.get("/users", response_model=list[UserRead])
async def list_users(db: AsyncSession = Depends(get_db)) -> list[User]:
    return list((await db.execute(select(User).order_by(User.id))).scalars().all())


@router.post("/users", response_model=UserRead, status_code=status.HTTP_201_CREATED)
async def create_user(payload: AdminUserCreate, db: AsyncSession = Depends(get_db)) -> User:
    existing = await db.execute(select(User).where(User.email == payload.email))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="email already registered")
    user = User(
        email=payload.email,
        hashed_password=hash_password(payload.password),
        full_name=payload.full_name,
        role=payload.role,
        status=STATUS_ACTIVE,  # created by an admin, so no approval step
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


@router.patch("/users/{user_id}", response_model=UserRead)
async def update_user(
    user_id: int, payload: AdminUserUpdate, db: AsyncSession = Depends(get_db)
) -> User:
    user = await db.get(User, user_id)
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
                .where(User.role == ROLE_ADMIN, User.status == STATUS_ACTIVE, User.id != user.id)
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
    return user


@router.get("/settings", response_model=SiteSettingsPayload)
async def read_settings(db: AsyncSession = Depends(get_db)) -> dict[str, str]:
    return await get_site_settings(db)


@router.put("/settings", response_model=SiteSettingsPayload)
async def update_settings(
    payload: SiteSettingsPayload, db: AsyncSession = Depends(get_db)
) -> dict[str, str]:
    for key, value in payload.model_dump().items():
        row = await db.get(SiteSetting, key)
        if row is None:
            db.add(SiteSetting(key=key, value=value))
        else:
            row.value = value
    await db.commit()
    return await get_site_settings(db)
