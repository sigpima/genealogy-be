from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from app.core.config import get_settings

ALGORITHM = "HS256"
BCRYPT_MAX_BYTES = 72  # bcrypt only ever reads this much of a password


class InvalidTokenError(Exception):
    pass


def _password_bytes(password: str) -> bytes:
    # Cut at the 72-byte limit exactly as the previous library did, so hashes made before the swap still verify and a very long
    # password neither crashes (bcrypt >= 5 refuses it) nor changes meaning.
    return password.encode("utf-8")[:BCRYPT_MAX_BYTES]


def hash_password(password: str) -> str:
    return bcrypt.hashpw(_password_bytes(password), bcrypt.gensalt()).decode("ascii")


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(_password_bytes(password), hashed.encode("utf-8"))
    except ValueError:  # not a bcrypt hash at all: a failed login, not a crash
        return False


def create_access_token(subject: str, expires_minutes: int | None = None) -> str:
    settings = get_settings()
    minutes = expires_minutes if expires_minutes is not None else settings.jwt_expire_minutes
    expire = datetime.now(timezone.utc) + timedelta(minutes=minutes)
    payload = {"sub": subject, "exp": expire}
    return jwt.encode(payload, settings.jwt_secret, algorithm=ALGORITHM)


def decode_access_token(token: str) -> str:
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[ALGORITHM], options={"require": ["exp"]})
    except jwt.PyJWTError as exc:
        raise InvalidTokenError("invalid or expired token") from exc
    subject = payload.get("sub")
    if not isinstance(subject, str) or not subject:
        raise InvalidTokenError("token missing subject")
    return subject
