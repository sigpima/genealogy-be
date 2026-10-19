"""The reminder job: before a giỗ or event, notify the users who asked for that many days of notice.

Idempotent on purpose: every reminder has a `dedupe_key` and `notifications` is unique on (user, key), so the worker can run
every hour, re-run after a crash, or catch up after being down, and nobody gets the same reminder twice.
"""

import asyncio
import logging
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import calendar_items
from app.core.calendar_items import Item, collect
from app.core.config import get_settings
from app.core.email import send_email
from app.core.retention import prune_notifications
from app.core.roles import STATUS_ACTIVE
from app.core.system_health import set_state
from app.models.event import Event
from app.models.member import Member
from app.models.notification import Notification
from app.models.tree import Tree
from app.models.user import User
from app.schemas.calendar import REMINDER_DAYS_ALLOWED

logger = logging.getLogger(__name__)


def _days_of(user: User) -> set[int]:
    return {int(d) for d in user.reminder_days.split(",") if d.strip().isdigit()} & set(REMINDER_DAYS_ALLOWED)


def _when(days: int) -> str:
    return "hôm nay" if days == 0 else "ngày mai" if days == 1 else f"{days} ngày nữa"


def _dedupe_key(item: Item, days: int) -> str:
    source = item.member_id if item.kind == "death_anniversary" else item.event_id
    return f"{item.kind}:{source}:{item.date.isoformat()}:{days}"


async def send_due_reminders(db: AsyncSession, today: date | None = None) -> dict[str, int]:
    """Create today's notifications (and emails) for every tree. Returns how many were created / emailed."""
    today = today or calendar_items.vn_today()
    smtp_on = bool(get_settings().smtp_host)
    created = emailed = 0
    for tree in (await db.execute(select(Tree).where(Tree.status == "active"))).scalars().all():  # a paused family gets nothing
        users = list(
            (await db.execute(select(User).where(User.tree_id == tree.id, User.status == STATUS_ACTIVE).order_by(User.id))).scalars().all()
        )
        wanted = set().union(*(_days_of(u) for u in users)) if users else set()
        if not wanted:
            continue
        members = list((await db.execute(select(Member).where(Member.tree_id == tree.id))).scalars().all())
        events = list((await db.execute(select(Event).where(Event.tree_id == tree.id))).scalars().all())
        by_date: dict[date, list[Item]] = {}
        for item in collect(members, events, today, today + timedelta(days=max(wanted))):
            by_date.setdefault(item.date, []).append(item)
        for user in users:
            for days in sorted(_days_of(user)):
                for item in by_date.get(today + timedelta(days=days), []):
                    link = f"/lich?ngay={item.date.isoformat()}"
                    title = f"{_when(days).capitalize()}: {item.title}"
                    body = f"{item.date:%d/%m/%Y} · {item.subtitle or ''}".strip(" ·")
                    inserted = (
                        await db.execute(
                            insert(Notification)
                            .values(
                                user_id=user.id,
                                tree_id=tree.id,
                                kind=item.kind,
                                title=title,
                                body=body,
                                link=link,
                                dedupe_key=_dedupe_key(item, days),
                            )
                            .on_conflict_do_nothing(constraint="uq_notifications_user_dedupe")
                            .returning(Notification.id)
                        )
                    ).first()
                    if inserted is None:
                        continue  # already sent on an earlier run
                    created += 1
                    if smtp_on and user.reminder_email:
                        try:
                            await asyncio.to_thread(send_email, user.email, f"[{tree.name}] {title}", f"{body}\n\n{item.description or ''}".strip())
                            emailed += 1
                        except Exception:  # noqa: BLE001 - the in-web notification already exists; a mail failure only costs the email
                            logger.warning("could not email reminder to %s", user.email, exc_info=True)
        await db.commit()
    await prune_notifications(db)  # old read reminders only; cheap and safe to repeat every pass
    await set_state(db, "reminders.last_run", datetime.now(timezone.utc).isoformat())  # once per pass, even when there was nothing to remind about
    await db.commit()
    return {"notifications": created, "emails": emailed}
