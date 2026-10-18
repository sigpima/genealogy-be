"""Security events in the audit log: failed logins against a real account and the lockout that follows.

The rate limiter (app/core/rate_limit.py) is in memory; these rows are what survives a restart and what the admin sees.
Nothing is written for unknown emails (nobody to tell) or for superadmins (no tree to show it in).
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.models.user import User


def record_failed_login(db: AsyncSession, user: User, failures_now: int, limit: int) -> None:
    """Add `security.login_failed` while the account is still under `limit` failures, and exactly one `security.locked`
    when the limit is reached; the attempts the limiter then refuses write nothing (no log flooding)."""
    if user.tree_id is None or failures_now > limit:
        return
    details = {"email": user.email, "failures": failures_now}
    audit.record(db, tree_id=user.tree_id, actor=user, action="security.login_failed", details=details)
    if failures_now == limit:
        audit.record(db, tree_id=user.tree_id, actor=user, action="security.locked", details=details)
