"""Groups of audit-log actions, for the admin's filter chips ("Dữ liệu", "Người dùng", "Bảo mật", "Cài đặt")."""

import datetime

from sqlalchemy import or_

from app.core.calendar_items import VN_TIMEZONE
from app.models.audit_log import AuditLog

#: kind -> action prefixes. Every prefix belongs to exactly one kind.
KINDS: dict[str, tuple[str, ...]] = {
    "data": (
        "member.", "marriage.", "branch.", "media.", "place.", "article.", "timeline.", "poem.",
        "event.", "card.", "request.", "data.", "book.",
    ),
    "people": ("user.",),
    "security": ("security.",),
    "settings": ("settings.", "privacy.", "calendar."),
}


def action_filter(kind: str):
    return or_(*[AuditLog.action.like(f"{prefix}%") for prefix in KINDS[kind]])


def day_start(day: datetime.date) -> datetime.datetime:
    """Midnight at the start of `day` in Vietnam time (the admins' calendar)."""
    return datetime.datetime.combine(day, datetime.time.min, tzinfo=VN_TIMEZONE)


def day_after(day: datetime.date) -> datetime.datetime:
    return day_start(day + datetime.timedelta(days=1))
