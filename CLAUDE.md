# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

- Install/sync dependencies: `uv sync`
- Run the dev server: `uv run uvicorn app.main:app --reload`
- Run all tests: `uv run pytest`
- Run a single test file: `uv run pytest tests/test_auth.py -v`
- Run a single test: `uv run pytest tests/test_auth.py::test_login_rejects_wrong_password -v`
- Apply migrations: `uv run alembic upgrade head`
- Create a new migration (requires a live Postgres reachable via `DATABASE_URL`, already at `head` for existing migrations — autogenerate diffs against its current state, not from scratch): `uv run alembic revision --autogenerate -m "message"`
- Seed the shared family tree from a `{name, children}` JSON file: `uv run python scripts/seed_members.py path/to/tree.json`

This project uses `uv`, not bare `pip`/`venv` — always prefix Python commands with `uv run`.

## Architecture

Async FastAPI backend for a genealogy app: auth (register/login/me/logout)
plus a `Member` CRUD API backing **one shared family tree** — there is no
per-user ownership, every logged-in user reads/writes the same tree (see
`docs/superpowers/specs/` for why).

**`Member` (`app/models/member.py`)** is a single self-referencing table:
`id`, `full_name`, `parent_id -> members.id` (nullable; `NULL` = root),
`birth_year`/`death_year` (nullable ints, year-only — no day/month, real
genealogy records rarely have more), `gender` (nullable, plain
`String(10)`, validated only at the Pydantic layer via `Gender(str, Enum)`
in `app/schemas/member.py` — not a native Postgres enum type, to keep
adding a new value a plain code change), `notes` (nullable `Text`,
unbounded — occupation and anything else not worth its own column goes
here), `created_at`. **When assigning a `Gender` value to `Member.gender`,
always use `payload.gender.value`, never the enum member directly** — a
`class X(str, Enum)` member is technically a `str` instance, but relying
on that instead of an explicit `.value` is fragile across Python versions
and DB drivers (`create_member`/`update_member` in
`app/routers/member.py` both do this correctly; follow that pattern for
any new enum-backed field). `app/routers/member.py`'s `GET /members/tree`
walks the whole table in one query and reconstructs it into the `{id,
name, birth_year, death_year, gender, notes, children}` shape the
frontend expects (`_build_tree`) — no recursive SQL, just a Python dict
keyed by `parent_id`. This is the *only* read endpoint for members (no
`GET /members/{id}`), so it deliberately returns full detail on every
node rather than just enough to draw the tree shape — the frontend needs
one fetch, not one-per-member-viewed. `PUT /members/{id}` prevents
creating a cycle by walking the *proposed* new parent's ancestor chain up
to the root and checking whether the member being updated shows up in it
(`_is_descendant`). `DELETE /members/{id}` relies on the FK's default
`RESTRICT` behavior — deleting a member that others reference as
`parent_id` raises `IntegrityError`, caught and turned into a 409; there
is no cascading delete, and none should be added without an explicit
product decision to allow it. All `/members/*` routes require auth via
the router-level `dependencies=[Depends(get_current_user)]`.

**Marriages (`app/models/marriage.py`)** let a member have one or more
recorded spouses over time. A `Marriage` row is just `member_id` +
`spouse_id` (both FK → `members.id`) + nullable `marriage_year` — a
spouse is an ordinary `Member` row (`parent_id` always `NULL`, no
children of its own) that happens to be referenced as `spouse_id` by
some `Marriage`. Both FKs are `ON DELETE CASCADE`, so **deleting a
spouse is just the existing `DELETE /members/{id}`** — no dedicated
"remove marriage" endpoint exists; the DB removes the `Marriage` row as
a side effect. `POST /members/{member_id}/marriages` creates the spouse
`Member` and the `Marriage` row together in one call (there is no flow
to marry two pre-existing tree members to each other); `PUT
/members/marriages/{marriage_id}` updates `marriage_year` and the
spouse's own fields together. Because spouses also have `parent_id =
NULL`, `_build_tree`'s root selection must exclude every id that
appears as a `spouse_id` in `marriages` — otherwise a member with two
spouses would produce three `parent_id IS NULL` rows and `root =
root_candidates[0]` could silently pick a spouse instead of the real
root. `GET /members/tree` attaches each member's `spouses` list by
grouping `marriages` by `member_id` (one extra `SELECT * FROM
marriages`, no N+1).

**Avatars (`Member.avatar_url`)** are stored as files on local disk
under `Settings.upload_dir` (env `UPLOAD_DIR`, default `uploads/`),
served back by FastAPI's `StaticFiles` mounted at `/uploads` in
`app/main.py` — `avatar_url` in the DB is always a path like
`/uploads/avatars/<uuid>.jpg`, never an absolute URL with a host.
`POST /members/{id}/avatar` (multipart, field `file`) validates content
type (`image/jpeg`/`png`/`webp` only) and size (5 MB max), deletes the
member's previous avatar file if one existed, writes the new one under
a random UUID filename, and updates `avatar_url`; `DELETE
/members/{id}/avatar` removes the file and clears the column. Only
top-level tree members get avatars — `SpouseInfo` has no `avatar_url`
field. **`app/main.py` creates `<upload_dir>/avatars/` at import time**
(`Path(settings.upload_dir, "avatars").mkdir(parents=True,
exist_ok=True)`) — without this, mounting `StaticFiles` raises
`RuntimeError` the moment `app.main` is imported, which is every single
test via the `client` fixture. Speaking of which: **`tests/conftest.py`'s
autouse `_env` fixture points `UPLOAD_DIR` at a per-test `tmp_path`**,
and a sibling `upload_dir` fixture exposes that same path so avatar
tests can assert on-disk file state — this keeps test runs from ever
writing into the repo's real `uploads/` folder (which is gitignored).

**Adding any new model requires updating `alembic/env.py`'s import
line**, not just creating the model file — `target_metadata = Base.metadata`
only knows about models that have actually been imported somewhere, and
`env.py`'s `from app.models import member, user` is what does that for
Alembic specifically (see the `Base.metadata.create_all` gotcha below,
which is the same underlying issue). Forgetting this makes
`alembic revision --autogenerate` silently generate an **empty**
migration instead of erroring — always open the generated file and
confirm it actually contains the expected `op.create_table(...)`.

**`scripts/seed_members.py`** is a one-off data loader (not an Alembic
migration — migrations manage schema, this loads data), used to import
`genealogy-web`'s static `new_treeData.json` into the `members` table. It
prepends `os.getcwd()` to `sys.path` the same way `alembic/env.py` does,
since running `python scripts/seed_members.py` otherwise puts `scripts/`
itself on `sys.path` rather than the project root, breaking the `app.*`
imports.

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

**Forgot password (`app/routers/auth.py`):** `POST /auth/forgot-password`
**always returns the same `200` body regardless of whether the email is
registered** — this anti-enumeration behavior is load-bearing, not
incidental; any future change to this endpoint must preserve identical
responses for known and unknown emails. If the email does match a user,
a `PasswordResetToken` row (`app/models/password_reset_token.py`) is
created — only a SHA-256 hash of the raw token is stored, the raw token
is only ever emailed — and `app/core/email.py`'s
`send_password_reset_email` (stdlib `smtplib`, configured via
`Settings.smtp_*`) is called through `asyncio.to_thread` so a slow SMTP
round-trip doesn't block the event loop. `POST /auth/reset-password`
redeems a token exactly once (`used_at` is set the moment the password
changes) and rejects unknown, expired, or already-used tokens with
`400`. **`expires_at`/`used_at` are naive UTC `DateTime` columns, not
`DateTime(timezone=True)`** — SQLite (used by every test via the
`client` fixture) silently drops tzinfo on round-trip, which would make
comparing against `datetime.now(timezone.utc)` raise `TypeError: can't
compare offset-naive and offset-aware datetimes` in tests while working
fine on real Postgres; staying naive-UTC end-to-end throughout
`_utcnow()`, the model, and every comparison sidesteps that dialect
mismatch entirely. Tests never send real email — they monkeypatch
`app.routers.auth.send_password_reset_email` directly (see
`tests/test_password_reset.py`); the one test that exercises
`app/core/email.py` itself monkeypatches `smtplib.SMTP`.

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

**SQLite does not enforce foreign keys by default** — `tests/conftest.py`'s
`client` fixture registers a `connect` event listener that runs
`PRAGMA foreign_keys=ON` on every new connection. Without it, tests
relying on FK-triggered behavior (e.g. `Member` delete-with-children
returning 409 via `IntegrityError`) would silently pass for the wrong
reason: SQLite would just allow the delete, and the code path that
catches `IntegrityError` would never actually run. Any new test fixture
that spins up its own SQLite engine and exercises FK-dependent behavior
needs the same event listener.
