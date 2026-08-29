# Forgot Password Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a user request a password-reset email and set a new password from a single-use, time-limited link, without leaking whether a given email is registered.

**Architecture:** A new `password_reset_tokens` table stores only a SHA-256 hash of each reset token (never the raw token) plus an expiry and a used-at marker. `POST /auth/forgot-password` always returns the same generic response regardless of whether the email exists; if it does, it emails a link via a new `app/core/email.py` (stdlib `smtplib`, no new dependency) run off the event loop via `asyncio.to_thread`. `POST /auth/reset-password` redeems a token exactly once. Two new frontend pages, `/forgot-password` and `/reset-password`, plus a one-line fix to an existing dead link.

**Tech Stack:** FastAPI, SQLAlchemy 2.0 async, Pydantic v2, Alembic, stdlib `smtplib` (backend, `genealogy-api/`); Next.js 15, React 19, TypeScript (frontend, `genealogy-web/`).

**Spec:** `docs/superpowers/specs/2026-08-29-forgot-password-design.md`

## Global Constraints

- `POST /auth/forgot-password` always responds `200` with the same body whether or not the email is registered — this anti-enumeration behavior is load-bearing, not incidental.
- A reset token is single-use: redeeming it sets `used_at`, and any later attempt with the same token is rejected regardless of expiry.
- `password_reset_tokens.expires_at`/`used_at` are stored as **naive UTC** `DateTime` (no `timezone=True`) and compared using a naive-UTC helper — SQLAlchemy's SQLite dialect silently drops tzinfo on round-trip for `DateTime(timezone=True)`, which would make `expires_at < datetime.now(timezone.utc)` raise `TypeError: can't compare offset-naive and offset-aware datetimes` in every test using the SQLite-backed `client` fixture, even though it would work on real Postgres. Staying naive-UTC end-to-end sidesteps the dialect mismatch entirely. `created_at` on this table keeps the existing `DateTime(timezone=True), server_default=func.now()` convention since it's DB-generated and never compared in Python.
- No real SMTP server exists in this dev environment — tests monkeypatch `app.routers.auth.send_password_reset_email` directly; the one test for `app/core/email.py` itself monkeypatches `smtplib.SMTP`. Manual/E2E verification (Task 7) uses a throwaway local debug SMTP sink via `uv run --with aiosmtpd`, never a real mailbox.
- Neither new frontend route needs a `middleware.ts` change — its `matcher` already only covers `/` and `/genealogy-tree`.
- Both repos are plain `main`-branch checkouts with no remote configured — commit directly to `main` in each repo per task.

---

### Task 1: `PasswordResetToken` model and migration

**Files:**
- Create: `genealogy-api/app/models/password_reset_token.py`
- Modify: `genealogy-api/alembic/env.py:13`
- Test: `genealogy-api/tests/test_password_reset_token_model.py`

**Interfaces:**
- Produces: `PasswordResetToken` (`id`, `user_id: int`, `token_hash: str`, `expires_at: datetime` naive UTC, `used_at: datetime | None` naive UTC, `created_at: datetime`) — consumed by Task 4 (router).

- [ ] **Step 1: Write the failing test**

Create `genealogy-api/tests/test_password_reset_token_model.py`:

```python
from datetime import datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


@pytest.fixture
async def session():
    from app.db.base import Base
    from app.models.password_reset_token import PasswordResetToken  # noqa: F401
    from app.models.user import User  # noqa: F401

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as s:
        yield s
    await engine.dispose()


async def test_create_password_reset_token(session):
    from app.models.password_reset_token import PasswordResetToken
    from app.models.user import User

    user = User(email="a@example.com", hashed_password="hashed", full_name="A B")
    session.add(user)
    await session.commit()
    await session.refresh(user)

    expires_at = datetime.utcnow() + timedelta(minutes=30)
    token = PasswordResetToken(user_id=user.id, token_hash="a" * 64, expires_at=expires_at)
    session.add(token)
    await session.commit()

    result = await session.execute(
        select(PasswordResetToken).where(PasswordResetToken.user_id == user.id)
    )
    fetched = result.scalar_one()
    assert fetched.token_hash == "a" * 64
    assert fetched.used_at is None
    assert fetched.created_at is not None
```

- [ ] **Step 2: Run the test to verify it fails**

Run (from `genealogy-api/`): `uv run pytest tests/test_password_reset_token_model.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.models.password_reset_token'`

- [ ] **Step 3: Write the model**

Create `genealogy-api/app/models/password_reset_token.py`:

```python
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class PasswordResetToken(Base):
    __tablename__ = "password_reset_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    # Naive UTC, not DateTime(timezone=True) - see Global Constraints in the
    # implementation plan: SQLite silently drops tzinfo on round-trip, which
    # would break expiry comparisons in tests but not in real Postgres.
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
```

Modify `genealogy-api/alembic/env.py` line 13 from:
```python
from app.models import marriage, member, user  # noqa: E402,F401  (registers models on Base.metadata)
```
to:
```python
from app.models import marriage, member, password_reset_token, user  # noqa: E402,F401  (registers models on Base.metadata)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/test_password_reset_token_model.py -v`
Expected: PASS

- [ ] **Step 5: Generate and apply the Alembic migration**

Requires the local Postgres service running, `DATABASE_URL` pointed at it, already at head.

Run: `uv run alembic revision --autogenerate -m "add password_reset_tokens table"`

Open the generated file under `genealogy-api/alembic/versions/` and confirm `upgrade()` contains an `op.create_table('password_reset_tokens', ...)` with a `sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE')` and a unique/indexed `token_hash` column.

Run: `uv run alembic upgrade head`
Expected: applies with no errors.

- [ ] **Step 6: Commit**

```bash
git add app/models/password_reset_token.py alembic/env.py alembic/versions/ tests/test_password_reset_token_model.py
git commit -m "feat: add PasswordResetToken model and migration"
```

---

### Task 2: SMTP settings and `app/core/email.py`

**Files:**
- Modify: `genealogy-api/app/core/config.py`
- Create: `genealogy-api/app/core/email.py`
- Modify: `genealogy-api/tests/test_config.py`
- Test: `genealogy-api/tests/test_email.py`

**Interfaces:**
- Produces: `Settings.smtp_host/smtp_port/smtp_username/smtp_password/smtp_from/smtp_use_tls`, `send_password_reset_email(to_email: str, reset_url: str) -> None` — consumed by Task 4.

- [ ] **Step 1: Write the failing settings tests**

Append to `genealogy-api/tests/test_config.py`:

```python
def test_settings_smtp_defaults(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@localhost/db")
    monkeypatch.setenv("JWT_SECRET", "test-secret")
    for var in ("SMTP_HOST", "SMTP_PORT", "SMTP_USERNAME", "SMTP_PASSWORD", "SMTP_FROM", "SMTP_USE_TLS"):
        monkeypatch.delenv(var, raising=False)

    settings = Settings(_env_file=None)

    assert settings.smtp_host == ""
    assert settings.smtp_port == 587
    assert settings.smtp_use_tls is True


def test_settings_reads_smtp_from_env(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@localhost/db")
    monkeypatch.setenv("JWT_SECRET", "test-secret")
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("SMTP_PORT", "2525")
    monkeypatch.setenv("SMTP_USERNAME", "bot@example.com")
    monkeypatch.setenv("SMTP_PASSWORD", "secret")
    monkeypatch.setenv("SMTP_FROM", "no-reply@example.com")
    monkeypatch.setenv("SMTP_USE_TLS", "false")

    settings = Settings(_env_file=None)

    assert settings.smtp_host == "smtp.example.com"
    assert settings.smtp_port == 2525
    assert settings.smtp_username == "bot@example.com"
    assert settings.smtp_password == "secret"
    assert settings.smtp_from == "no-reply@example.com"
    assert settings.smtp_use_tls is False
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_config.py -v`
Expected: FAIL — `AttributeError: 'Settings' object has no attribute 'smtp_host'`

- [ ] **Step 3: Add the settings**

In `genealogy-api/app/core/config.py`, change:

```python
    upload_dir: str = "uploads"
```

to:

```python
    upload_dir: str = "uploads"
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    smtp_use_tls: bool = True
```

- [ ] **Step 4: Run the settings tests to verify they pass**

Run: `uv run pytest tests/test_config.py -v`
Expected: PASS (8 tests)

- [ ] **Step 5: Write the failing email test**

Create `genealogy-api/tests/test_email.py`:

```python
class _FakeSMTP:
    instances: list["_FakeSMTP"] = []

    def __init__(self, host, port):
        self.host = host
        self.port = port
        self.started_tls = False
        self.login_args = None
        self.sent_message = None
        _FakeSMTP.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def starttls(self):
        self.started_tls = True

    def login(self, username, password):
        self.login_args = (username, password)

    def send_message(self, message):
        self.sent_message = message


def test_send_password_reset_email_sends_via_smtp(monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("SMTP_PORT", "2525")
    monkeypatch.setenv("SMTP_USERNAME", "bot@example.com")
    monkeypatch.setenv("SMTP_PASSWORD", "secret")
    from app.core.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setattr("smtplib.SMTP", _FakeSMTP)
    _FakeSMTP.instances.clear()

    from app.core.email import send_password_reset_email

    send_password_reset_email("user@example.com", "http://x/reset-password?token=abc")

    assert len(_FakeSMTP.instances) == 1
    fake = _FakeSMTP.instances[0]
    assert fake.host == "smtp.example.com"
    assert fake.port == 2525
    assert fake.started_tls is True
    assert fake.login_args == ("bot@example.com", "secret")
    assert fake.sent_message["To"] == "user@example.com"
    assert "reset-password?token=abc" in fake.sent_message.get_payload()

    get_settings.cache_clear()
```

- [ ] **Step 6: Run the test to verify it fails**

Run: `uv run pytest tests/test_email.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.core.email'`

- [ ] **Step 7: Write the email module**

Create `genealogy-api/app/core/email.py`:

```python
import smtplib
from email.mime.text import MIMEText

from app.core.config import get_settings


def send_password_reset_email(to_email: str, reset_url: str) -> None:
    settings = get_settings()
    message = MIMEText(
        "You requested a password reset. Click the link below to choose a "
        f"new password:\n\n{reset_url}\n\nThis link expires in 30 minutes. "
        "If you did not request this, ignore this email."
    )
    message["Subject"] = "Reset your password"
    message["From"] = settings.smtp_from or settings.smtp_username
    message["To"] = to_email

    with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as server:
        if settings.smtp_use_tls:
            server.starttls()
        if settings.smtp_username:
            server.login(settings.smtp_username, settings.smtp_password)
        server.send_message(message)
```

- [ ] **Step 8: Run the test to verify it passes**

Run: `uv run pytest tests/test_email.py -v`
Expected: PASS

Run: `uv run pytest`
Expected: full suite passes (no regressions).

- [ ] **Step 9: Commit**

```bash
git add app/core/config.py app/core/email.py tests/test_config.py tests/test_email.py
git commit -m "feat: add SMTP settings and password-reset email sender"
```

---

### Task 3: `ForgotPasswordRequest` / `ResetPasswordRequest` schemas

**Files:**
- Modify: `genealogy-api/app/schemas/auth.py`
- Test: `genealogy-api/tests/test_schemas.py`

**Interfaces:**
- Produces: `ForgotPasswordRequest(email: EmailStr)`, `ResetPasswordRequest(token: str, new_password: str)` — consumed by Task 4.

- [ ] **Step 1: Write the failing tests**

Append to `genealogy-api/tests/test_schemas.py`:

```python
def test_forgot_password_request_requires_valid_email():
    from app.schemas.auth import ForgotPasswordRequest

    with pytest.raises(ValidationError):
        ForgotPasswordRequest(email="not-an-email")


def test_reset_password_request_rejects_short_password():
    from app.schemas.auth import ResetPasswordRequest

    with pytest.raises(ValidationError):
        ResetPasswordRequest(token="abc", new_password="short")


def test_reset_password_request_accepts_valid_data():
    from app.schemas.auth import ResetPasswordRequest

    data = ResetPasswordRequest(token="abc", new_password="longenough")
    assert data.token == "abc"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_schemas.py -v`
Expected: FAIL — `ImportError: cannot import name 'ForgotPasswordRequest' from 'app.schemas.auth'`

- [ ] **Step 3: Add the schemas**

Replace the full contents of `genealogy-api/app/schemas/auth.py`:

```python
from pydantic import BaseModel, EmailStr, Field


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str = Field(min_length=8)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_schemas.py -v`
Expected: PASS (8 tests)

- [ ] **Step 5: Commit**

```bash
git add app/schemas/auth.py tests/test_schemas.py
git commit -m "feat: add forgot/reset password request schemas"
```

---

### Task 4: `POST /auth/forgot-password` and `POST /auth/reset-password`

**Files:**
- Modify: `genealogy-api/app/routers/auth.py`
- Test: `genealogy-api/tests/test_password_reset.py`

**Interfaces:**
- Consumes: `PasswordResetToken` (Task 1), `send_password_reset_email` (Task 2), `ForgotPasswordRequest`/`ResetPasswordRequest` (Task 3).

- [ ] **Step 1: Write the failing tests**

Create `genealogy-api/tests/test_password_reset.py`:

```python
async def test_forgot_password_existing_user_sends_email(client, monkeypatch):
    sent = []
    monkeypatch.setattr(
        "app.routers.auth.send_password_reset_email",
        lambda to_email, reset_url: sent.append({"to_email": to_email, "reset_url": reset_url}),
    )

    await client.post(
        "/auth/register",
        json={"email": "a@example.com", "password": "old-password", "full_name": "A B"},
    )

    response = await client.post("/auth/forgot-password", json={"email": "a@example.com"})
    assert response.status_code == 200
    assert len(sent) == 1
    assert sent[0]["to_email"] == "a@example.com"
    assert "/reset-password?token=" in sent[0]["reset_url"]


async def test_forgot_password_nonexistent_user_does_not_send_email(client, monkeypatch):
    sent = []
    monkeypatch.setattr(
        "app.routers.auth.send_password_reset_email", lambda *args: sent.append(args)
    )

    response = await client.post("/auth/forgot-password", json={"email": "nobody@example.com"})
    assert response.status_code == 200
    assert sent == []


async def test_reset_password_with_valid_token_changes_password(client, monkeypatch):
    sent = []
    monkeypatch.setattr(
        "app.routers.auth.send_password_reset_email",
        lambda to_email, reset_url: sent.append(reset_url),
    )

    await client.post(
        "/auth/register",
        json={"email": "a@example.com", "password": "old-password", "full_name": "A B"},
    )
    await client.post("/auth/forgot-password", json={"email": "a@example.com"})
    token = sent[0].split("token=")[1]

    response = await client.post(
        "/auth/reset-password", json={"token": token, "new_password": "new-password"}
    )
    assert response.status_code == 204

    old_login = await client.post(
        "/auth/login", json={"email": "a@example.com", "password": "old-password"}
    )
    assert old_login.status_code == 401

    new_login = await client.post(
        "/auth/login", json={"email": "a@example.com", "password": "new-password"}
    )
    assert new_login.status_code == 200


async def test_reset_password_rejects_unknown_token(client):
    response = await client.post(
        "/auth/reset-password", json={"token": "does-not-exist", "new_password": "new-password"}
    )
    assert response.status_code == 400


async def test_reset_password_rejects_expired_token(client, monkeypatch):
    sent = []
    monkeypatch.setattr(
        "app.routers.auth.send_password_reset_email",
        lambda to_email, reset_url: sent.append(reset_url),
    )
    monkeypatch.setattr("app.routers.auth.RESET_TOKEN_EXPIRE_MINUTES", -1)

    await client.post(
        "/auth/register",
        json={"email": "a@example.com", "password": "old-password", "full_name": "A B"},
    )
    await client.post("/auth/forgot-password", json={"email": "a@example.com"})
    token = sent[0].split("token=")[1]

    response = await client.post(
        "/auth/reset-password", json={"token": token, "new_password": "new-password"}
    )
    assert response.status_code == 400


async def test_reset_password_rejects_reused_token(client, monkeypatch):
    sent = []
    monkeypatch.setattr(
        "app.routers.auth.send_password_reset_email",
        lambda to_email, reset_url: sent.append(reset_url),
    )

    await client.post(
        "/auth/register",
        json={"email": "a@example.com", "password": "old-password", "full_name": "A B"},
    )
    await client.post("/auth/forgot-password", json={"email": "a@example.com"})
    token = sent[0].split("token=")[1]

    first = await client.post(
        "/auth/reset-password", json={"token": token, "new_password": "new-password"}
    )
    assert first.status_code == 204

    second = await client.post(
        "/auth/reset-password", json={"token": token, "new_password": "another-password"}
    )
    assert second.status_code == 400


async def test_reset_password_rejects_short_password(client, monkeypatch):
    sent = []
    monkeypatch.setattr(
        "app.routers.auth.send_password_reset_email",
        lambda to_email, reset_url: sent.append(reset_url),
    )
    await client.post(
        "/auth/register",
        json={"email": "a@example.com", "password": "old-password", "full_name": "A B"},
    )
    await client.post("/auth/forgot-password", json={"email": "a@example.com"})
    token = sent[0].split("token=")[1]

    response = await client.post(
        "/auth/reset-password", json={"token": token, "new_password": "short"}
    )
    assert response.status_code == 422
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_password_reset.py -v`
Expected: FAIL — `404 Not Found` for both new routes.

- [ ] **Step 3: Write the endpoints**

In `genealogy-api/app/routers/auth.py`, change the import block from:

```python
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.security import (
    InvalidTokenError,
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)
from app.db.session import get_db
from app.models.user import User
from app.schemas.auth import LoginRequest, TokenResponse
from app.schemas.user import UserCreate, UserRead

router = APIRouter(prefix="/auth", tags=["auth"])

ACCESS_TOKEN_COOKIE = "access_token"
```

to:

```python
import asyncio
import hashlib
import secrets
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.email import send_password_reset_email
from app.core.security import (
    InvalidTokenError,
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)
from app.db.session import get_db
from app.models.password_reset_token import PasswordResetToken
from app.models.user import User
from app.schemas.auth import (
    ForgotPasswordRequest,
    LoginRequest,
    ResetPasswordRequest,
    TokenResponse,
)
from app.schemas.user import UserCreate, UserRead

router = APIRouter(prefix="/auth", tags=["auth"])

ACCESS_TOKEN_COOKIE = "access_token"
RESET_TOKEN_EXPIRE_MINUTES = 30


def _utcnow() -> datetime:
    # Naive UTC on purpose - see the implementation plan's Global Constraints
    # for why this table avoids DateTime(timezone=True).
    return datetime.utcnow()


def _hash_reset_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()
```

Then add these two endpoints at the end of the file:

```python
@router.post("/forgot-password")
async def forgot_password(
    payload: ForgotPasswordRequest, db: AsyncSession = Depends(get_db)
) -> dict[str, str]:
    result = await db.execute(select(User).where(User.email == payload.email))
    user = result.scalar_one_or_none()

    if user is not None:
        raw_token = secrets.token_urlsafe(32)
        reset_token = PasswordResetToken(
            user_id=user.id,
            token_hash=_hash_reset_token(raw_token),
            expires_at=_utcnow() + timedelta(minutes=RESET_TOKEN_EXPIRE_MINUTES),
        )
        db.add(reset_token)
        await db.commit()

        settings = get_settings()
        reset_url = f"{settings.frontend_origin}/reset-password?token={raw_token}"
        await asyncio.to_thread(send_password_reset_email, user.email, reset_url)

    return {"detail": "if that email exists, a reset link has been sent"}


@router.post("/reset-password", status_code=status.HTTP_204_NO_CONTENT)
async def reset_password(
    payload: ResetPasswordRequest, db: AsyncSession = Depends(get_db)
) -> None:
    token_hash = _hash_reset_token(payload.token)
    result = await db.execute(
        select(PasswordResetToken).where(PasswordResetToken.token_hash == token_hash)
    )
    reset_token = result.scalar_one_or_none()

    if (
        reset_token is None
        or reset_token.used_at is not None
        or reset_token.expires_at < _utcnow()
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="invalid or expired token"
        )

    user = await db.get(User, reset_token.user_id)
    user.hashed_password = hash_password(payload.new_password)
    reset_token.used_at = _utcnow()
    await db.commit()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_password_reset.py -v`
Expected: PASS (7 tests)

Run: `uv run pytest`
Expected: full suite passes (no regressions in existing auth/member/marriage/avatar tests).

- [ ] **Step 5: Commit**

```bash
git add app/routers/auth.py tests/test_password_reset.py
git commit -m "feat: add forgot-password and reset-password endpoints"
```

---

### Task 5: `/forgot-password` page and the dead-link fix

**Files:**
- Modify: `genealogy-web/src/components/FormExtra.tsx`
- Create: `genealogy-web/src/app/forgot-password/page.tsx`
- Create: `genealogy-web/src/app/forgot-password/components/forgotPasswordForm.tsx`

- [ ] **Step 1: Point the existing link at the new page**

Replace the full contents of `genealogy-web/src/components/FormExtra.tsx`:

```tsx
import Link from 'next/link';

export default function FormExtra() {
  return (
    <div className="flex items-center justify-between">
      <div className="flex items-center">
        <input id="remember-me" name="remember-me" type="checkbox" className="size-4 rounded border-default" />
        <label htmlFor="remember-me" className="ml-2 block text-sm text-default">
          Remember me
        </label>
      </div>

      <div className="text-sm">
        <Link href="/forgot-password" className="font-medium accent-text hover:underline">
          Forgot your password?
        </Link>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Create the form component**

Create `genealogy-web/src/app/forgot-password/components/forgotPasswordForm.tsx`:

```tsx
'use client';

import { useState } from 'react';
import FormAction from '@/components/FormAction';
import Input from '@/components/Input';

export default function ForgotPasswordForm() {
  const [email, setEmail] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setIsSubmitting(true);
    try {
      const response = await fetch('/api/auth/forgot-password', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email }),
      });
      if (!response.ok) {
        setError('Không thể gửi yêu cầu. Vui lòng thử lại.');
        return;
      }
      setSubmitted(true);
    } catch {
      setError('Không thể kết nối tới máy chủ. Vui lòng thử lại.');
    } finally {
      setIsSubmitting(false);
    }
  };

  if (submitted) {
    return (
      <p className="mt-8 text-center text-sm text-default">
        Nếu email này tồn tại, chúng tôi đã gửi một liên kết đặt lại mật khẩu. Vui lòng
        kiểm tra hộp thư của bạn.
      </p>
    );
  }

  return (
    <form className="mt-8 space-y-6" onSubmit={handleSubmit}>
      <Input
        handleChange={(e) => setEmail(e.target.value)}
        value={email}
        labelText="Email address"
        labelFor="email-address"
        id="email-address"
        name="email"
        type="email"
        isRequired
        placeholder="Email address"
      />
      {error && <p className="text-sm text-danger">{error}</p>}
      <FormAction text={isSubmitting ? 'Đang gửi...' : 'Gửi liên kết đặt lại'} />
    </form>
  );
}
```

- [ ] **Step 3: Create the page**

Create `genealogy-web/src/app/forgot-password/page.tsx`:

```tsx
import AuthHeader from '@/components/auth/AuthHeader';
import ForgotPasswordForm from './components/forgotPasswordForm';

export default function ForgotPasswordPage() {
  return (
    <div className="flex h-screen min-h-full items-center justify-center bg-app px-4 py-12 sm:px-6 lg:px-8">
      <div className="w-full max-w-md space-y-8">
        <AuthHeader
          heading="Quên mật khẩu"
          paragraph="Đã nhớ mật khẩu? "
          linkName="Đăng nhập"
          linkUrl="/login"
        />
        <ForgotPasswordForm />
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Verify**

Run (from `genealogy-web/`): `npx tsc --noEmit`
Expected: no errors.

Run: `npm run lint`
Expected: no errors.

Run: `npx vitest run`
Expected: PASS (14 tests) — unaffected.

- [ ] **Step 5: Commit**

```bash
git add src/components/FormExtra.tsx src/app/forgot-password
git commit -m "feat: add forgot-password page and fix the dead link to it"
```

---

### Task 6: `/reset-password` page

**Files:**
- Create: `genealogy-web/src/app/reset-password/page.tsx`
- Create: `genealogy-web/src/app/reset-password/components/resetPasswordForm.tsx`

- [ ] **Step 1: Create the form component**

Create `genealogy-web/src/app/reset-password/components/resetPasswordForm.tsx`:

```tsx
'use client';

import { useRouter, useSearchParams } from 'next/navigation';
import { useState } from 'react';
import FormAction from '@/components/FormAction';
import Input from '@/components/Input';

export default function ResetPasswordForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const token = searchParams.get('token') ?? '';

  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);

    if (!token) {
      setError('Liên kết không hợp lệ. Vui lòng yêu cầu đặt lại mật khẩu lại.');
      return;
    }
    if (newPassword !== confirmPassword) {
      setError('Mật khẩu xác nhận không khớp.');
      return;
    }

    setIsSubmitting(true);
    try {
      const response = await fetch('/api/auth/reset-password', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ token, new_password: newPassword }),
      });
      if (!response.ok) {
        setError('Liên kết đã hết hạn hoặc không hợp lệ. Vui lòng yêu cầu liên kết mới.');
        return;
      }
      router.push('/login');
    } catch {
      setError('Không thể kết nối tới máy chủ. Vui lòng thử lại.');
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <form className="mt-8 space-y-6" onSubmit={handleSubmit}>
      <Input
        handleChange={(e) => setNewPassword(e.target.value)}
        value={newPassword}
        labelText="New password"
        labelFor="new-password"
        id="new-password"
        name="new-password"
        type="password"
        isRequired
        placeholder="Mật khẩu mới"
      />
      <Input
        handleChange={(e) => setConfirmPassword(e.target.value)}
        value={confirmPassword}
        labelText="Confirm new password"
        labelFor="confirm-new-password"
        id="confirm-new-password"
        name="confirm-new-password"
        type="password"
        isRequired
        placeholder="Xác nhận mật khẩu mới"
      />
      {error && <p className="text-sm text-danger">{error}</p>}
      <FormAction text={isSubmitting ? 'Đang lưu...' : 'Đặt lại mật khẩu'} />
    </form>
  );
}
```

- [ ] **Step 2: Create the page with a `Suspense` boundary**

Create `genealogy-web/src/app/reset-password/page.tsx`:

```tsx
import { Suspense } from 'react';
import AuthHeader from '@/components/auth/AuthHeader';
import ResetPasswordForm from './components/resetPasswordForm';

export default function ResetPasswordPage() {
  return (
    <div className="flex h-screen min-h-full items-center justify-center bg-app px-4 py-12 sm:px-6 lg:px-8">
      <div className="w-full max-w-md space-y-8">
        <AuthHeader
          heading="Đặt lại mật khẩu"
          paragraph="Đã nhớ mật khẩu? "
          linkName="Đăng nhập"
          linkUrl="/login"
        />
        <Suspense fallback={null}>
          <ResetPasswordForm />
        </Suspense>
      </div>
    </div>
  );
}
```

`useSearchParams()` requires a `Suspense` boundary in Next 15's App Router
for pages that can be statically prerendered — omitting it fails `next
build` with "useSearchParams() should be wrapped in a suspense boundary".

- [ ] **Step 3: Verify**

Run: `npx tsc --noEmit`
Expected: no errors.

Run: `npm run lint`
Expected: no errors.

Run: `npx vitest run`
Expected: PASS (14 tests).

Run: `npm run build` (with no dev server running against the same `.next` directory)
Expected: succeeds, including prerendering `/reset-password` without the Suspense error described above.

- [ ] **Step 4: Commit**

```bash
git add src/app/reset-password
git commit -m "feat: add reset-password page"
```

---

### Task 7: End-to-end verification and docs refresh

**Files:**
- No new source files. Verification only, plus `CLAUDE.md` refresh in both repos.

- [ ] **Step 1: Full backend test suite**

Run (from `genealogy-api/`): `uv run pytest`
Expected: all tests pass.

- [ ] **Step 2: Full frontend checks (already covered per-task, re-run once more together)**

Run (from `genealogy-web/`): `npx tsc --noEmit && npm run lint && npx vitest run && npm run build`
Expected: all pass.

- [ ] **Step 3: Start a local debug SMTP sink**

Run as a background process: `uv run --with aiosmtpd python -m aiosmtpd -n -l localhost:1025`
This prints every received message's raw text (headers + body) to its own
stdout — no real email is sent anywhere. `--with aiosmtpd` is an ephemeral
`uv` dependency for this one invocation; it must not be added to
`pyproject.toml`.

- [ ] **Step 4: Start both application servers with the sink configured**

Start `genealogy-api` with the debug sink as its SMTP target:
```bash
SMTP_HOST=localhost SMTP_PORT=1025 SMTP_USE_TLS=false uv run uvicorn app.main:app --reload --port 8000
```
Start `genealogy-web` normally: `npm run dev`.

- [ ] **Step 5: Browser verification with Playwright**

Write a script (in the session's scratch/temp directory) that:
1. Registers a fresh test user via `/signup` with a known password.
2. Goes to `/login`, clicks "Forgot your password?", confirms it lands on
   `/forgot-password`.
3. Submits that user's email, confirms the generic success message
   appears.
4. Reads the debug SMTP sink's captured stdout (via the background
   process's output) to extract the `token=` query parameter from the
   emailed `reset_url`.
5. Navigates to `/reset-password?token=<that token>`, submits a new
   password, confirms it redirects to `/login`.
6. Logs in with the new password (succeeds) and confirms the old
   password now fails (`/auth/login` via a direct API call or a failed
   login attempt in the UI).
7. Submits `/forgot-password` again with an email that was never
   registered and confirms the exact same generic success message
   appears (no visible difference, confirming the anti-enumeration
   behavior end-to-end).

Run it against the two running servers and confirm every step passes.

- [ ] **Step 6: Clean up test data**

Delete the test user created in Step 5 via the API if it's not something
you want left in the shared user table (unlike the shared family tree,
the `users` table is not the "one shared tree" data — deleting a leftover
test *account* is still good hygiene since email addresses must be
unique). Do not use `psql -c` for any cleanup involving non-ASCII text.

- [ ] **Step 7: Stop the sink and both servers**

Kill the port 3000, port 8000, and port 1025 listeners/processes.

- [ ] **Step 8: Refresh `CLAUDE.md` in both repos**

In `genealogy-api/CLAUDE.md`, add a short paragraph describing the
`password_reset_tokens` table, the naive-UTC datetime decision, the
`Settings` SMTP fields, `app/core/email.py`, and the two new endpoints
(mention the anti-enumeration behavior explicitly, since it's easy for a
future change to accidentally break by returning different responses
for known vs. unknown emails).

In `genealogy-web/CLAUDE.md`, add a short paragraph describing the two
new pages, the `Suspense` requirement for `useSearchParams()` in
`/reset-password`, and that the "Forgot your password?" link in
`FormExtra.tsx` used to be a dead `href="#"`.

Commit each repo's `CLAUDE.md` change separately:

```bash
# in genealogy-api/
git add CLAUDE.md
git commit -m "docs: document the forgot-password flow"
```

```bash
# in genealogy-web/
git add CLAUDE.md
git commit -m "docs: document the forgot/reset password pages"
```
