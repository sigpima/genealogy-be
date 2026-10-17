"""My in-web notifications (created by the reminder job)."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.notification import Notification
from app.models.user import User
from app.routers.auth import get_current_user
from app.schemas.calendar import MarkRead, NotificationList, NotificationRead

router = APIRouter(prefix="/notifications", tags=["notifications"])


async def _list(db: AsyncSession, user: User, limit: int) -> NotificationList:
    unread = (
        await db.execute(
            select(func.count()).select_from(Notification).where(Notification.user_id == user.id, Notification.read_at.is_(None))
        )
    ).scalar_one()
    rows = (
        await db.execute(select(Notification).where(Notification.user_id == user.id).order_by(Notification.id.desc()).limit(limit))
    ).scalars().all()
    return NotificationList(
        unread=unread,
        items=[
            NotificationRead(
                id=n.id, kind=n.kind, title=n.title, body=n.body, link=n.link, created_at=n.created_at.isoformat(), read=n.read_at is not None
            )
            for n in rows
        ],
    )


@router.get("", response_model=NotificationList)
async def list_notifications(
    limit: int = Query(default=30, ge=1, le=100), db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
) -> NotificationList:
    return await _list(db, user, limit)


@router.post("/read", response_model=NotificationList)
async def mark_read(payload: MarkRead, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)) -> NotificationList:
    """Mark some (or all) of MY notifications read; ids that belong to somebody else are ignored."""
    statement = update(Notification).where(Notification.user_id == user.id, Notification.read_at.is_(None)).values(read_at=func.now())
    if payload.ids is not None:
        statement = statement.where(Notification.id.in_(payload.ids))
    await db.execute(statement)
    await db.commit()
    return await _list(db, user, 30)
