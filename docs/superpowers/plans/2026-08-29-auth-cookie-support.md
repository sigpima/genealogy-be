# Auth Cookie + CORS Support Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let `genealogy-web` authenticate against this API using an httpOnly cookie instead of only a bearer token in the response body, with CORS configured for the frontend's origin, plus a logout endpoint.

**Architecture:** `/auth/login` sets an `access_token` httpOnly cookie (still also returns the JSON token body, unchanged, for existing callers/tests). A new token-extraction dependency checks the cookie first, falls back to the `Authorization` header. `/auth/logout` clears the cookie. `CORSMiddleware` is added to `app.main` with the frontend origin and credentials allowed.

**Tech Stack:** Same as the existing backend (FastAPI, SQLAlchemy async, pytest/httpx).

**Spec:** `docs/superpowers/specs/2026-08-29-auth-cookie-support-design.md`

## Global Constraints

- `/auth/login`'s existing JSON response body (`TokenResponse`) is unchanged — the cookie is additive, not a replacement, so existing tests/behavior keep working.
- `Authorization: Bearer` header auth must keep working after this change (needed for non-browser API testing) — cookie takes priority when both are present, but either alone must work.
- `cookie_secure` defaults to `False` (plain `http://localhost` dev); `.env.example` must document setting it `True` behind HTTPS.
- No JWT verification changes — `decode_access_token`/`create_access_token` (`app/core/security.py`) are untouched by this plan.

---

## File Structure

```
genealogy-api/
  app/
    core/
      config.py       # modified: + frontend_origin, cookie_secure
    main.py            # modified: + CORSMiddleware
    routers/
      auth.py           # modified: cookie set on login, cookie-or-header extraction, new /logout
  tests/
    test_config.py       # modified: + tests for the 2 new settings fields
    test_auth.py           # modified: + cookie/logout tests
  .env.example              # modified: + FRONTEND_ORIGIN, COOKIE_SECURE
```

---

### Task 1: Settings + CORS middleware

**Files:**
- Modify: `app/core/config.py`, `app/main.py`, `.env.example`
- Test: `tests/test_config.py`

**Interfaces:**
- Produces: `Settings.frontend_origin: str` (default `"http://localhost:3000"`), `Settings.cookie_secure: bool` (default `False`).

- [ ] **Step 1: Write the failing test**

Add to `tests/test_config.py`:

```python
def test_settings_defaults_for_frontend_origin_and_cookie_secure(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@localhost/db")
    monkeypatch.setenv("JWT_SECRET", "test-secret")
    monkeypatch.delenv("FRONTEND_ORIGIN", raising=False)
    monkeypatch.delenv("COOKIE_SECURE", raising=False)

    settings = Settings(_env_file=None)

    assert settings.frontend_origin == "http://localhost:3000"
    assert settings.cookie_secure is False


def test_settings_reads_frontend_origin_and_cookie_secure_from_env(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@localhost/db")
    monkeypatch.setenv("JWT_SECRET", "test-secret")
    monkeypatch.setenv("FRONTEND_ORIGIN", "https://example.com")
    monkeypatch.setenv("COOKIE_SECURE", "true")

    settings = Settings(_env_file=None)

    assert settings.frontend_origin == "https://example.com"
    assert settings.cookie_secure is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_config.py -v`
Expected: FAIL — `TypeError` / `ValidationError` mentioning `frontend_origin`/`cookie_secure` are not recognized fields, or `AttributeError` on the assertion.

- [ ] **Step 3: Add the settings fields**

In `app/core/config.py`, add to the `Settings` class (after `jwt_expire_minutes`):

```python
    frontend_origin: str = "http://localhost:3000"
    cookie_secure: bool = False
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_config.py -v`
Expected: 4 passed

- [ ] **Step 5: Add CORS middleware**

Replace `app/main.py` with:

```python
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.config import get_settings
from app.routers.auth import router as auth_router

settings = get_settings()

app = FastAPI(title="genealogy-api")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(status_code=500, content={"detail": "internal server error"})
```

- [ ] **Step 6: Update `.env.example`**

Append to `.env.example`:

```
FRONTEND_ORIGIN=http://localhost:3000
COOKIE_SECURE=false
```

- [ ] **Step 7: Run the full test suite to confirm nothing broke**

Run: `uv run pytest -v`
Expected: all tests pass (22 existing + 2 new = 24 passed). `app.main`'s new module-level `get_settings()` call is safe here because `tests/conftest.py`'s `_env` fixture is `autouse=True` and every `app.main` import in the test suite happens inside a test function body (never at module top-level), so env vars are always set first.

- [ ] **Step 8: Commit**

```bash
git add app/core/config.py app/main.py .env.example tests/test_config.py
git commit -m "feat: add frontend_origin/cookie_secure settings and CORS middleware"
```

---

### Task 2: Cookie-based auth + logout endpoint

**Files:**
- Modify: `app/routers/auth.py`
- Test: `tests/test_auth.py`

**Interfaces:**
- Consumes: `get_settings()` (Task 1).
- Produces: `POST /auth/logout`; `/auth/login` now also sets an `access_token` cookie; `get_current_user` now accepts either the cookie or the `Authorization` header.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_auth.py`:

```python
async def test_login_sets_httponly_cookie(client):
    await client.post(
        "/auth/register",
        json={"email": "cookie@example.com", "password": "longenough", "full_name": "A B"},
    )
    response = await client.post(
        "/auth/login", json={"email": "cookie@example.com", "password": "longenough"}
    )
    set_cookie = response.headers.get("set-cookie", "")
    assert "access_token=" in set_cookie
    assert "httponly" in set_cookie.lower()


async def test_me_succeeds_via_cookie_alone(client):
    await client.post(
        "/auth/register",
        json={"email": "cookie2@example.com", "password": "longenough", "full_name": "A B"},
    )
    await client.post(
        "/auth/login", json={"email": "cookie2@example.com", "password": "longenough"}
    )
    # httpx.AsyncClient's cookie jar carries the cookie from the login response automatically.
    response = await client.get("/auth/me")
    assert response.status_code == 200
    assert response.json()["email"] == "cookie2@example.com"


async def test_logout_clears_cookie_and_me_then_requires_header(client):
    await client.post(
        "/auth/register",
        json={"email": "cookie3@example.com", "password": "longenough", "full_name": "A B"},
    )
    await client.post(
        "/auth/login", json={"email": "cookie3@example.com", "password": "longenough"}
    )
    logout_response = await client.post("/auth/logout")
    assert logout_response.status_code == 200

    response = await client.get("/auth/me")
    assert response.status_code == 401
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_auth.py -v`
Expected: FAIL — `test_login_sets_httponly_cookie` fails (`access_token=` not in `Set-Cookie` header — currently no cookie is set at all), `test_logout_clears_cookie_and_me_then_requires_header` fails with a 404 on `POST /auth/logout` (route doesn't exist yet).

- [ ] **Step 3: Write the implementation**

Replace `app/routers/auth.py` with:

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


def get_token_from_request(request: Request) -> str:
    cookie_token = request.cookies.get(ACCESS_TOKEN_COOKIE)
    if cookie_token:
        return cookie_token
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.lower().startswith("bearer "):
        return auth_header[7:]
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="not authenticated")


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
async def login(
    payload: LoginRequest, response: Response, db: AsyncSession = Depends(get_db)
) -> TokenResponse:
    result = await db.execute(select(User).where(User.email == payload.email))
    user = result.scalar_one_or_none()
    if user is None or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid credentials"
        )

    token = create_access_token(subject=user.email)
    settings = get_settings()
    response.set_cookie(
        key=ACCESS_TOKEN_COOKIE,
        value=token,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        max_age=settings.jwt_expire_minutes * 60,
        path="/",
    )
    return TokenResponse(access_token=token)


@router.post("/logout")
async def logout(response: Response) -> dict[str, str]:
    response.delete_cookie(ACCESS_TOKEN_COOKIE, path="/")
    return {"detail": "logged out"}


async def get_current_user(
    token: str = Depends(get_token_from_request), db: AsyncSession = Depends(get_db)
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

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_auth.py -v`
Expected: 9 passed (6 existing + 3 new)

- [ ] **Step 5: Commit**

```bash
git add app/routers/auth.py tests/test_auth.py
git commit -m "feat: set httpOnly auth cookie on login, add logout, accept cookie or header"
```

---

### Task 3: Full verification + CLAUDE.md refresh

- [ ] **Step 1: Run the full test suite**

Run: `uv run pytest -v`
Expected: 27 passed (24 from Task 1 + 3 more from Task 2 — Task 1's count already included the pre-existing 22, so the running total after Task 2 is 22 + 2 + 3 = 27).

- [ ] **Step 2: Refresh CLAUDE.md**

Invoke the `init` skill (Skill tool, `skill: "init"`) for this repository — it should update the auth-flow description to mention the cookie and `/auth/logout`.

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: refresh CLAUDE.md for cookie auth and logout"
```

---

## Self-Review Notes

- **Spec coverage:** cookie set on login ✓ (Task 2), cookie-or-header extraction ✓ (Task 2), `/auth/logout` ✓ (Task 2), CORS with credentials ✓ (Task 1), settings additions ✓ (Task 1), `.env.example` updated ✓ (Task 1). Non-goals (refresh tokens, edge JWT verification, CSRF beyond SameSite=Lax) untouched.
- **Placeholder scan:** none — every step has literal code or an exact command with expected output.
- **Type consistency:** `ACCESS_TOKEN_COOKIE` defined once in `auth.py` and reused in both `login` and `logout`; `get_token_from_request` signature matches its use as a `Depends` in `get_current_user`.
