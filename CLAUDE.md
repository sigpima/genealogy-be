# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

- Install/sync dependencies: `uv sync`
- Run the dev server: `uv run uvicorn app.main:app --reload`
- Run all tests: `uv run pytest`
- Run a single test file: `uv run pytest tests/test_auth.py -v`
- Run a single test: `uv run pytest tests/test_auth.py::test_login_rejects_wrong_password -v`
- Apply migrations: `uv run alembic upgrade head`
- Create a new migration (requires a live Postgres reachable via `DATABASE_URL`, since autogenerate diffs against it): `uv run alembic revision --autogenerate -m "message"`

This project uses `uv`, not bare `pip`/`venv` — always prefix Python commands with `uv run`.

## Architecture

Async FastAPI backend for a genealogy app, currently scoped to **auth only**
(register/login/me). Member/Family/Grant data model is an intentionally
separate, not-yet-built phase — see `docs/superpowers/specs/` for the design
history and rationale before adding it.

**Two database engines, deliberately separate:**
- The app itself uses SQLAlchemy 2.0 **async** (`asyncpg` driver) via
  `app/db/session.py`'s `get_engine()`/`get_db()`.
- Alembic migrations run through a **sync** engine (`psycopg2`), configured
  in `alembic/env.py`. `_sync_database_url()` derives the sync URL by
  string-replacing `+asyncpg` with `+psycopg2` in `Settings.database_url` —
  there is only one `DATABASE_URL` env var, not two.

**Settings (`app/core/config.py`)** are read once via `get_settings()`
(`@lru_cache`-wrapped) from `.env` / environment: `DATABASE_URL`,
`JWT_SECRET`, `JWT_EXPIRE_MINUTES`, `FRONTEND_ORIGIN`, `COOKIE_SECURE`.
Never hardcode these — this replaced a legacy Spring Boot backend that had
a hardcoded JWT secret and a committed plaintext DB password, and that
mistake shouldn't recur. Tests call `get_settings.cache_clear()` after
monkeypatching env vars, since the cache would otherwise leak stale
settings between tests.

**`app/main.py` calls `get_settings()` at module import time** (to build
`CORSMiddleware`'s `allow_origins` when the `FastAPI` app object is
constructed — middleware config isn't a per-request `Depends`, it's fixed
once at app-construction time). This is only safe because every test that
imports `app.main` does so inside a test function body, and
`tests/conftest.py`'s `_env` fixture (`autouse=True`) always sets
`DATABASE_URL`/`JWT_SECRET` before any test body runs. Don't move an
`import app.main` (or `from app.main import ...`) to module top-level in a
test file — that would import it before `_env` has a chance to set env
vars.

**Request/response boundary rule:** every endpoint accepts/returns a
Pydantic schema (`app/schemas/`), never a raw SQLAlchemy model
(`app/models/`). This is deliberate — the legacy backend returned the `User`
entity directly from `/auth/register`, leaking the password hash in the
response body.

**Auth flow (`app/routers/auth.py`):** `hash_password`/`verify_password`
(passlib+bcrypt) and `create_access_token`/`decode_access_token`
(python-jose, HS256) live in `app/core/security.py`, independent of the
router. `POST /auth/login` returns the token in the JSON body **and**
sets it as an httpOnly `access_token` cookie (`SameSite=Lax`, `Secure`
gated by `Settings.cookie_secure`) — the cookie is for the browser
frontend, the JSON body stays for non-browser API callers/tests.
`get_token_from_request` reads the cookie first, falling back to an
`Authorization: Bearer` header; `get_current_user` (used by `GET
/auth/me`) depends on it, decoding via `decode_access_token` and catching
`InvalidTokenError` to return 401. `POST /auth/logout` clears the cookie.
Note the pinned versions in `pyproject.toml`: `passlib==1.7.4` +
`bcrypt==4.0.1` — bcrypt >=4.1 removed an attribute passlib 1.7.4 reads,
so don't bump `bcrypt` alone without also moving off passlib.

**Import-order gotcha for SQLAlchemy metadata:** `Base.metadata.create_all`
(used in test fixtures, see `tests/conftest.py` and `tests/test_user_model.py`)
only creates tables for models that have already been imported somewhere —
SQLAlchemy registers a model on `Base.metadata` at class-definition time.
Fixtures that call `create_all` import the relevant model module (or
`app.main`, which transitively imports all routers/models) *before* calling
it, not after.

**Global error handling:** `app/main.py` registers a catch-all
`@app.exception_handler(Exception)` that returns a generic 500 JSON body
instead of leaking stack traces; domain errors (duplicate email, bad
credentials, invalid token) are raised as `HTTPException` in the router
directly.

## Testing

Tests never touch a real Postgres — `tests/conftest.py`'s `client` fixture
overrides the `get_db` FastAPI dependency with a fresh in-memory SQLite
(`sqlite+aiosqlite:///:memory:`) engine per test, and the `_env` fixture
(autouse) points `DATABASE_URL` at SQLite for the duration of the test.
`asyncio_mode = "auto"` is set in `pyproject.toml`, so async test functions
and fixtures don't need `@pytest.mark.asyncio`.
