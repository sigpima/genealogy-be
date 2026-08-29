# FastAPI Auth Backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up `genealogy-api`, an async FastAPI backend providing register/login/me, replacing the retired Spring Boot backend's auth slice with the security issues fixed.

**Architecture:** FastAPI app on SQLAlchemy 2.0 async (asyncpg) with a `User` model, JWT auth via `python-jose`, `passlib[bcrypt]` hashing, Pydantic schemas at every API boundary, Alembic migrations run through a separate sync (`psycopg2`) engine. Tests run against an in-memory SQLite (`aiosqlite`) engine via `pytest-asyncio` + `httpx.AsyncClient`.

**Tech Stack:** Python 3.12, `uv` (dependency/venv manager), FastAPI, SQLAlchemy 2.0 async, asyncpg, Alembic, psycopg2-binary, pydantic-settings, passlib+bcrypt, python-jose, pytest/pytest-asyncio/httpx/aiosqlite.

**Spec:** `docs/superpowers/specs/2026-08-29-fastapi-auth-backend-design.md`

## Global Constraints

- Use `uv` for all dependency/venv management (`uv sync`, `uv run ...`) — Python >=3.12.
- SQLAlchemy 2.0 **async** throughout the app; Alembic migrations use a **separate sync engine** (`psycopg2`) purely for migration execution — the app itself never uses this engine at runtime.
- `JWT_SECRET` and `DATABASE_URL` come from environment variables only (via `pydantic-settings` reading `.env`) — never hardcoded, never committed. `.env` is gitignored; `.env.example` documents the shape.
- Passwords hashed with `passlib[bcrypt]`; pin `passlib==1.7.4` and `bcrypt==4.0.1` together (bcrypt >=4.1 removes an attribute passlib 1.7.4 reads — this pin avoids a known crash).
- Every endpoint request/response uses a Pydantic schema — never accept or return a raw SQLAlchemy model to/from the client (this was the legacy password-leak bug).
- Member/Family/Grant models and endpoints are **out of scope** for this plan — auth only.
- Tests run against an in-memory SQLite engine (`sqlite+aiosqlite:///:memory:`) via `pytest-asyncio` (`asyncio_mode = "auto"`) and `httpx.AsyncClient` — never a real Postgres in the unit/integration suite.

---

## File Structure

```
genealogy-api/
  app/
    __init__.py
    core/
      __init__.py
      config.py       # Settings (pydantic-settings), get_settings()
      security.py      # hash_password, verify_password, create/decode_access_token
    db/
      __init__.py
      base.py           # declarative Base
      session.py        # get_engine(), get_session_maker(), get_db() dependency
    models/
      __init__.py
      user.py            # User ORM model
    schemas/
      __init__.py
      user.py             # UserCreate, UserRead
      auth.py             # LoginRequest, TokenResponse
    routers/
      __init__.py
      auth.py              # POST /auth/register, /auth/login, GET /auth/me
    main.py                 # FastAPI app, router wiring, global exception handler
  alembic/
    env.py
    script.py.mako
    versions/
      <rev>_create_users_table.py
  alembic.ini
  tests/
    __init__.py
    test_config.py
    test_security.py
    test_user_model.py
    test_schemas.py
    conftest.py
    test_main.py
    test_auth.py
  .env.example
  .gitignore
  pyproject.toml
  README.md
```

---

### Task 1: Project scaffolding

**Files:**
- Create: `pyproject.toml`
- Create: `.gitignore`
- Create: `.env.example`
- Create: `README.md`
- Create: `app/__init__.py`, `app/core/__init__.py`, `app/db/__init__.py`, `app/models/__init__.py`, `app/schemas/__init__.py`, `app/routers/__init__.py`, `tests/__init__.py` (all empty)

**Interfaces:**
- Produces: an installable `uv` project with all runtime + dev dependencies resolvable, and the empty package skeleton later tasks fill in.

- [ ] **Step 1: Create `pyproject.toml`**

```toml
[project]
name = "genealogy-api"
version = "0.1.0"
description = "Genealogy app auth backend (FastAPI, async)"
requires-python = ">=3.12"
dependencies = [
    "fastapi>=0.115.0",
    "uvicorn[standard]>=0.32.0",
    "sqlalchemy>=2.0.36",
    "asyncpg>=0.30.0",
    "alembic>=1.13.3",
    "psycopg2-binary>=2.9.9",
    "pydantic-settings>=2.6.0",
    "python-dotenv>=1.0.1",
    "email-validator>=2.2.0",
    "passlib==1.7.4",
    "bcrypt==4.0.1",
    "python-jose[cryptography]>=3.3.0",
]

[dependency-groups]
dev = [
    "pytest>=8.3.3",
    "pytest-asyncio>=0.24.0",
    "httpx>=0.27.2",
    "aiosqlite>=0.20.0",
]

[tool.pytest.ini_options]
asyncio_mode = "auto"
```

- [ ] **Step 2: Create `.gitignore`**

```
.venv/
__pycache__/
*.pyc
.env
.pytest_cache/
*.egg-info/
.coverage
```

- [ ] **Step 3: Create `.env.example`**

```
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/genealogy
JWT_SECRET=change-me-to-a-random-secret
JWT_EXPIRE_MINUTES=60
```

- [ ] **Step 4: Create `README.md`**

```markdown
# genealogy-api

Async FastAPI backend for the genealogy app — auth only in this phase
(register/login/me). Member/Family CRUD is a future phase (see
`docs/superpowers/specs/`).

## Setup

    uv sync
    cp .env.example .env   # edit JWT_SECRET and DATABASE_URL for your machine

## Run

    uv run uvicorn app.main:app --reload

## Test

    uv run pytest

## Migrations

    uv run alembic upgrade head          # apply migrations
    uv run alembic revision --autogenerate -m "message"   # create a new one
```

- [ ] **Step 5: Create empty package `__init__.py` files**

Create these files, each with empty content:
`app/__init__.py`, `app/core/__init__.py`, `app/db/__init__.py`,
`app/models/__init__.py`, `app/schemas/__init__.py`,
`app/routers/__init__.py`, `tests/__init__.py`

- [ ] **Step 6: Install dependencies**

Run: `uv sync`
Expected: completes without error, creates `.venv/` and `uv.lock`.

- [ ] **Step 7: Verify imports resolve**

Run: `uv run python -c "import fastapi, sqlalchemy, alembic, jose, passlib, asyncpg, aiosqlite, pydantic_settings; print('ok')"`
Expected output: `ok`

- [ ] **Step 8: Commit**

```bash
git add pyproject.toml .gitignore .env.example README.md app tests uv.lock
git commit -m "chore: scaffold genealogy-api project"
```

---

### Task 2: Settings (config)

**Files:**
- Create: `app/core/config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Produces: `Settings(BaseSettings)` with fields `database_url: str`, `jwt_secret: str`, `jwt_expire_minutes: int = 60`; `get_settings() -> Settings` (`@lru_cache`-wrapped, has `.cache_clear()`).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_config.py
from app.core.config import Settings


def test_settings_loads_from_env(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@localhost/db")
    monkeypatch.setenv("JWT_SECRET", "test-secret")
    monkeypatch.setenv("JWT_EXPIRE_MINUTES", "30")

    settings = Settings(_env_file=None)

    assert settings.database_url == "postgresql+asyncpg://u:p@localhost/db"
    assert settings.jwt_secret == "test-secret"
    assert settings.jwt_expire_minutes == 30


def test_settings_jwt_expire_minutes_defaults_to_60(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@localhost/db")
    monkeypatch.setenv("JWT_SECRET", "test-secret")
    monkeypatch.delenv("JWT_EXPIRE_MINUTES", raising=False)

    settings = Settings(_env_file=None)

    assert settings.jwt_expire_minutes == 60
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_config.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.core.config'`

- [ ] **Step 3: Write minimal implementation**

```python
# app/core/config.py
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    jwt_secret: str
    jwt_expire_minutes: int = 60


@lru_cache
def get_settings() -> Settings:
    return Settings()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_config.py -v`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add app/core/config.py tests/test_config.py
git commit -m "feat: add Settings config"
```

---

### Task 3: Security utilities (hashing + JWT)

**Files:**
- Create: `app/core/security.py`
- Test: `tests/test_security.py`

**Interfaces:**
- Consumes: `get_settings()` from Task 2 (`settings.jwt_secret`, `settings.jwt_expire_minutes`).
- Produces: `hash_password(password: str) -> str`, `verify_password(password: str, hashed: str) -> bool`, `create_access_token(subject: str, expires_minutes: int | None = None) -> str`, `decode_access_token(token: str) -> str` (returns the subject), `InvalidTokenError(Exception)`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_security.py
import pytest

from app.core.config import get_settings


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@localhost/db")
    monkeypatch.setenv("JWT_SECRET", "test-secret")
    monkeypatch.setenv("JWT_EXPIRE_MINUTES", "60")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_hash_password_roundtrip():
    from app.core.security import hash_password, verify_password

    hashed = hash_password("s3cret-pass")
    assert hashed != "s3cret-pass"
    assert verify_password("s3cret-pass", hashed) is True


def test_verify_password_rejects_wrong_password():
    from app.core.security import hash_password, verify_password

    hashed = hash_password("s3cret-pass")
    assert verify_password("wrong-pass", hashed) is False


def test_create_and_decode_access_token_roundtrip():
    from app.core.security import create_access_token, decode_access_token

    token = create_access_token(subject="user@example.com")
    assert decode_access_token(token) == "user@example.com"


def test_decode_access_token_rejects_expired_token():
    from app.core.security import InvalidTokenError, create_access_token, decode_access_token

    token = create_access_token(subject="user@example.com", expires_minutes=-1)
    with pytest.raises(InvalidTokenError):
        decode_access_token(token)


def test_decode_access_token_rejects_garbage_token():
    from app.core.security import InvalidTokenError, decode_access_token

    with pytest.raises(InvalidTokenError):
        decode_access_token("not-a-real-token")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_security.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.core.security'`

- [ ] **Step 3: Write minimal implementation**

```python
# app/core/security.py
from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import get_settings

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

ALGORITHM = "HS256"


class InvalidTokenError(Exception):
    pass


def hash_password(password: str) -> str:
    return _pwd_context.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    return _pwd_context.verify(password, hashed)


def create_access_token(subject: str, expires_minutes: int | None = None) -> str:
    settings = get_settings()
    minutes = expires_minutes if expires_minutes is not None else settings.jwt_expire_minutes
    expire = datetime.now(timezone.utc) + timedelta(minutes=minutes)
    payload = {"sub": subject, "exp": expire}
    return jwt.encode(payload, settings.jwt_secret, algorithm=ALGORITHM)


def decode_access_token(token: str) -> str:
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[ALGORITHM])
    except JWTError as exc:
        raise InvalidTokenError("invalid or expired token") from exc
    subject = payload.get("sub")
    if subject is None:
        raise InvalidTokenError("token missing subject")
    return subject
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_security.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add app/core/security.py tests/test_security.py
git commit -m "feat: add password hashing and JWT helpers"
```

---

### Task 4: DB base, async session, User model

**Files:**
- Create: `app/db/base.py`
- Create: `app/db/session.py`
- Create: `app/models/user.py`
- Test: `tests/test_user_model.py`

**Interfaces:**
- Consumes: `get_settings()` from Task 2.
- Produces: `Base` (declarative base, `app.db.base.Base`), `get_db()` async generator dependency (`app.db.session.get_db`), `User` ORM model (`app.models.user.User`) with `id: int`, `email: str`, `hashed_password: str`, `full_name: str`, `created_at: datetime`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_user_model.py
import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


@pytest.fixture
async def session():
    from app.db.base import Base

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as s:
        yield s
    await engine.dispose()


async def test_create_and_query_user(session):
    from app.models.user import User

    user = User(email="a@example.com", hashed_password="hashed", full_name="A B")
    session.add(user)
    await session.commit()

    result = await session.execute(select(User).where(User.email == "a@example.com"))
    fetched = result.scalar_one()

    assert fetched.id is not None
    assert fetched.full_name == "A B"
    assert fetched.created_at is not None


async def test_email_unique_constraint(session):
    from app.models.user import User

    session.add(User(email="dup@example.com", hashed_password="h1", full_name="X"))
    await session.commit()

    session.add(User(email="dup@example.com", hashed_password="h2", full_name="Y"))
    with pytest.raises(IntegrityError):
        await session.commit()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_user_model.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.db.base'`

- [ ] **Step 3: Write minimal implementation**

```python
# app/db/base.py
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass
```

```python
# app/db/session.py
from collections.abc import AsyncGenerator
from functools import lru_cache

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings


@lru_cache
def get_engine():
    settings = get_settings()
    return create_async_engine(settings.database_url, echo=False)


def get_session_maker() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(get_engine(), expire_on_commit=False)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    session_maker = get_session_maker()
    async with session_maker() as session:
        yield session
```

```python
# app/models/user.py
from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_user_model.py -v`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add app/db/base.py app/db/session.py app/models/user.py tests/test_user_model.py
git commit -m "feat: add async DB session and User model"
```

---

### Task 5: Pydantic schemas

**Files:**
- Create: `app/schemas/user.py`
- Create: `app/schemas/auth.py`
- Test: `tests/test_schemas.py`

**Interfaces:**
- Produces: `UserCreate(email, password, full_name)`, `UserRead(id, email, full_name, created_at)` (with `from_attributes=True`), `LoginRequest(email, password)`, `TokenResponse(access_token, token_type="bearer")`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_schemas.py
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError


def test_user_create_accepts_valid_data():
    from app.schemas.user import UserCreate

    data = UserCreate(email="a@example.com", password="longenough", full_name="A B")
    assert data.email == "a@example.com"


def test_user_create_rejects_invalid_email():
    from app.schemas.user import UserCreate

    with pytest.raises(ValidationError):
        UserCreate(email="not-an-email", password="longenough", full_name="A B")


def test_user_create_rejects_short_password():
    from app.schemas.user import UserCreate

    with pytest.raises(ValidationError):
        UserCreate(email="a@example.com", password="short", full_name="A B")


def test_user_read_from_attributes():
    from app.schemas.user import UserRead

    class FakeUser:
        id = 1
        email = "a@example.com"
        full_name = "A B"
        created_at = datetime.now(timezone.utc)

    read = UserRead.model_validate(FakeUser())
    assert read.id == 1
    assert read.email == "a@example.com"


def test_token_response_defaults_token_type_to_bearer():
    from app.schemas.auth import TokenResponse

    token = TokenResponse(access_token="abc123")
    assert token.token_type == "bearer"


def test_login_request_requires_email_and_password():
    from app.schemas.auth import LoginRequest

    with pytest.raises(ValidationError):
        LoginRequest(email="a@example.com")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_schemas.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.schemas.user'`

- [ ] **Step 3: Write minimal implementation**

```python
# app/schemas/user.py
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    full_name: str = Field(min_length=1)


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: EmailStr
    full_name: str
    created_at: datetime
```

```python
# app/schemas/auth.py
from pydantic import BaseModel, EmailStr


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_schemas.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add app/schemas/user.py app/schemas/auth.py tests/test_schemas.py
git commit -m "feat: add auth Pydantic schemas"
```

---

### Task 6: Auth API — router, app wiring, tests

**Files:**
- Create: `app/routers/auth.py`
- Create: `app/main.py`
- Create: `tests/conftest.py`
- Create: `tests/test_main.py`
- Create: `tests/test_auth.py`

**Interfaces:**
- Consumes: `get_db` (Task 4), `User` (Task 4), `UserCreate`/`UserRead`/`LoginRequest`/`TokenResponse` (Task 5), `hash_password`/`verify_password`/`create_access_token`/`decode_access_token`/`InvalidTokenError` (Task 3).
- Produces: `app.main.app` (FastAPI instance) with `POST /auth/register`, `POST /auth/login`, `GET /auth/me`; `app.main.unhandled_exception_handler`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/conftest.py
from collections.abc import AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
    monkeypatch.setenv("JWT_SECRET", "test-secret")
    monkeypatch.setenv("JWT_EXPIRE_MINUTES", "60")
    from app.core.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
async def client(_env) -> AsyncGenerator[AsyncClient, None]:
    from app.db.base import Base
    from app.db.session import get_db
    from app.main import app

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_maker = async_sessionmaker(engine, expire_on_commit=False)

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        async with session_maker() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()
    await engine.dispose()
```

```python
# tests/test_main.py
import asyncio

from fastapi import Request


def test_unhandled_exception_handler_returns_500_json():
    from app.main import unhandled_exception_handler

    request = Request(scope={"type": "http", "headers": []})
    response = asyncio.run(unhandled_exception_handler(request, RuntimeError("boom")))
    assert response.status_code == 500
```

```python
# tests/test_auth.py
async def test_register_returns_user_without_password(client):
    response = await client.post(
        "/auth/register",
        json={"email": "a@example.com", "password": "longenough", "full_name": "A B"},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["email"] == "a@example.com"
    assert "password" not in body
    assert "hashed_password" not in body


async def test_register_rejects_duplicate_email(client):
    payload = {"email": "dup@example.com", "password": "longenough", "full_name": "A B"}
    await client.post("/auth/register", json=payload)
    response = await client.post("/auth/register", json=payload)
    assert response.status_code == 409


async def test_login_returns_token_for_correct_credentials(client):
    await client.post(
        "/auth/register",
        json={"email": "a@example.com", "password": "longenough", "full_name": "A B"},
    )
    response = await client.post(
        "/auth/login", json={"email": "a@example.com", "password": "longenough"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]


async def test_login_rejects_wrong_password(client):
    await client.post(
        "/auth/register",
        json={"email": "a@example.com", "password": "longenough", "full_name": "A B"},
    )
    response = await client.post(
        "/auth/login", json={"email": "a@example.com", "password": "wrong-pass"}
    )
    assert response.status_code == 401


async def test_me_returns_current_user_with_valid_token(client):
    await client.post(
        "/auth/register",
        json={"email": "a@example.com", "password": "longenough", "full_name": "A B"},
    )
    login_response = await client.post(
        "/auth/login", json={"email": "a@example.com", "password": "longenough"}
    )
    token = login_response.json()["access_token"]

    response = await client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert response.json()["email"] == "a@example.com"


async def test_me_rejects_missing_token(client):
    response = await client.get("/auth/me")
    assert response.status_code == 401
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_main.py tests/test_auth.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.main'`

- [ ] **Step 3: Write minimal implementation**

```python
# app/routers/auth.py
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

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
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


@router.post("/register", response_model=UserRead, status_code=status.HTTP_201_CREATED)
async def register(payload: UserCreate, db: AsyncSession = Depends(get_db)) -> User:
    existing = await db.execute(select(User).where(User.email == payload.email))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="email already registered"
        )

    user = User(
        email=payload.email,
        hashed_password=hash_password(payload.password),
        full_name=payload.full_name,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


@router.post("/login", response_model=TokenResponse)
async def login(payload: LoginRequest, db: AsyncSession = Depends(get_db)) -> TokenResponse:
    result = await db.execute(select(User).where(User.email == payload.email))
    user = result.scalar_one_or_none()
    if user is None or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid credentials"
        )

    token = create_access_token(subject=user.email)
    return TokenResponse(access_token=token)


async def get_current_user(
    token: str = Depends(oauth2_scheme), db: AsyncSession = Depends(get_db)
) -> User:
    try:
        email = decode_access_token(token)
    except InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid or expired token"
        )

    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="user not found")
    return user


@router.get("/me", response_model=UserRead)
async def read_current_user(current_user: User = Depends(get_current_user)) -> User:
    return current_user
```

```python
# app/main.py
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.routers.auth import router as auth_router

app = FastAPI(title="genealogy-api")

app.include_router(auth_router)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(status_code=500, content={"detail": "internal server error"})
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_main.py tests/test_auth.py -v`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add app/routers/auth.py app/main.py tests/conftest.py tests/test_main.py tests/test_auth.py
git commit -m "feat: add auth API (register, login, me)"
```

---

### Task 7: Alembic migrations

**Files:**
- Create: `alembic.ini`, `alembic/env.py`, `alembic/script.py.mako`, `alembic/versions/<rev>_create_users_table.py` (generated)

**Interfaces:**
- Consumes: `Base` and `User` from Task 4, `get_settings()` from Task 2.
- Produces: a working `alembic upgrade head` / `alembic downgrade base` cycle creating/dropping the `users` table.

- [ ] **Step 1: Scaffold Alembic**

Run: `uv run alembic init alembic`
Expected: creates `alembic.ini`, `alembic/env.py`, `alembic/script.py.mako`, `alembic/versions/`.

- [ ] **Step 2: Rewrite `alembic/env.py` to use the app's models and settings**

```python
# alembic/env.py
import os
import sys
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context

sys.path.append(os.getcwd())

from app.core.config import get_settings  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.models import user  # noqa: E402,F401  (registers User on Base.metadata)

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _sync_database_url() -> str:
    settings = get_settings()
    return settings.database_url.replace("+asyncpg", "+psycopg2")


def run_migrations_offline() -> None:
    url = _sync_database_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = _sync_database_url()
    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
```

- [ ] **Step 3: Comment out the unused static URL in `alembic.ini`**

In `alembic.ini`, find the line `sqlalchemy.url = driver://user:pass@localhost/dbname` and comment it out (prefix with `#`), adding above it:
`# URL is set programmatically in env.py from Settings.database_url`

- [ ] **Step 4: Start a throwaway Postgres for migration generation/verification**

Run: `docker run --rm -d --name genealogy-api-pg-tmp -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=genealogy -p 5433:5432 postgres:16`
Then wait for readiness:
Run: `docker exec genealogy-api-pg-tmp sh -c "until pg_isready -U postgres; do sleep 1; done"`
Expected: eventually prints `accepting connections`.

- [ ] **Step 5: Generate the initial migration**

Run (with env vars for this command only):
`DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5433/genealogy JWT_SECRET=tmp uv run alembic revision --autogenerate -m "create users table"`
Expected: creates `alembic/versions/<rev>_create_users_table.py` containing an `op.create_table("users", ...)` with columns `id`, `email`, `hashed_password`, `full_name`, `created_at`.

- [ ] **Step 6: Verify the migration applies cleanly**

Run: `DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5433/genealogy JWT_SECRET=tmp uv run alembic upgrade head`
Expected: no errors, ends with the new revision id.

- [ ] **Step 7: Verify the downgrade path works**

Run: `DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5433/genealogy JWT_SECRET=tmp uv run alembic downgrade base`
Expected: no errors, `users` table dropped.

- [ ] **Step 8: Tear down the throwaway Postgres**

Run: `docker stop genealogy-api-pg-tmp`
Expected: container stops and is removed (started with `--rm`).

- [ ] **Step 9: Commit**

```bash
git add alembic.ini alembic/env.py alembic/script.py.mako alembic/versions
git commit -m "feat: add Alembic migrations for users table"
```

---

### Task 8: Full suite verification + CLAUDE.md

**Files:**
- None created by this task's own steps except `CLAUDE.md` (generated by the `init` skill).

- [ ] **Step 1: Run the full test suite**

Run: `uv run pytest -v`
Expected: all tests from Tasks 2-6 pass (20 passed).

- [ ] **Step 2: Generate CLAUDE.md**

Invoke the `init` skill (Skill tool, `skill: "init"`) for this repository to generate `CLAUDE.md` documenting the actual resulting structure.

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: add CLAUDE.md"
```

---

## Self-Review Notes

- **Spec coverage:** register/login/me ✓ (Task 6), JWT via env secret ✓ (Task 2/3), DB URL via env ✓ (Task 2), no password in responses ✓ (Task 5/6 tests), global exception handler ✓ (Task 6), Pydantic validation ✓ (Task 5), folder structure ✓ (matches spec exactly), Alembic with sync engine ✓ (Task 7), testing plan (hash/verify, token roundtrip/expiry, register/login/me happy+sad paths) ✓ (Tasks 3 & 6), CLAUDE.md via `init` skill ✓ (Task 8). Member/Family explicitly out of scope, matches spec's non-goals.
- **Placeholder scan:** no TBD/TODO; every step has literal code or an exact command with expected output.
- **Type consistency:** `User` fields (`id`, `email`, `hashed_password`, `full_name`, `created_at`) match across Task 4 (model), Task 5 (`UserRead`), Task 6 (router); `get_settings()`/`.cache_clear()` used consistently in Tasks 2, 3, 4, 6; `InvalidTokenError` raised in Task 3, caught in Task 6.
