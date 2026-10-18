"""Invitation links (`/moi/<token>`): making, hashing and judging them. The token itself is never stored."""

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from app.models.member_invite import MemberInvite

LIFETIME = timedelta(days=14)


def utcnow() -> datetime:
    """Naive UTC, like the password-reset tokens (see `app/routers/auth.py::_utcnow`)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def new_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def invite_status(invite: MemberInvite, now: datetime) -> str:
    """'used' | 'revoked' | 'expired' | 'pending' (in that order of precedence)."""
    if invite.used_at is not None:
        return "used"
    if invite.revoked_at is not None:
        return "revoked"
    if invite.expires_at <= now:
        return "expired"
    return "pending"
