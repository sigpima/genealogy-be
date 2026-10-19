"""Housekeeping that keeps the tables from growing forever."""

from sqlalchemy import delete, or_, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditLog
from app.models.notification import Notification

READ_NOTIFICATION_DAYS = 90
ANY_NOTIFICATION_DAYS = 365


async def prune_notifications(db: AsyncSession, read_days: int = READ_NOTIFICATION_DAYS, any_days: int = ANY_NOTIFICATION_DAYS) -> int:
    """Delete notifications that were read more than `read_days` ago (by creation date), and any that is older than `any_days`
    (a reminder nobody opened in a year is dead). Reminders only look 30 days ahead, so a deleted one can never be created again."""
    result = await db.execute(
        delete(Notification).where(
            or_(
                (Notification.read_at.is_not(None)) & (Notification.created_at < text(f"now() - interval '{int(read_days)} days'")),
                Notification.created_at < text(f"now() - interval '{int(any_days)} days'"),
            )
        )
    )
    await db.commit()
    return result.rowcount or 0


async def prune_audit(db: AsyncSession, days: int) -> int:
    """Delete audit entries older than `days`. Never run automatically: the log is the families' history; the owner chooses (manage.py prune)."""
    if days < 1:
        raise ValueError("days must be at least 1")
    result = await db.execute(delete(AuditLog).where(AuditLog.created_at < text(f"now() - interval '{int(days)} days'")))
    await db.commit()
    return result.rowcount or 0
