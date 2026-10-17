# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

- Install/sync dependencies: `uv sync`
- Run the dev server: `uv run uvicorn app.main:app --reload`
- Run all tests (needs `docker compose up -d --wait db-test` first): `uv run pytest`
- Run a single test file: `uv run pytest tests/test_auth.py -v`
- Run a single test: `uv run pytest tests/test_auth.py::test_login_rejects_wrong_password -v`
- Apply migrations: `uv run alembic upgrade head`
- Create a new migration (requires a live Postgres reachable via `DATABASE_URL`, already at `head` for existing migrations — autogenerate diffs against its current state, not from scratch): `uv run alembic revision --autogenerate -m "message"`
- Seed the shared family tree from a `{name, children}` JSON file: `uv run python scripts/seed_members.py path/to/tree.json`

This project uses `uv`, not bare `pip`/`venv` — always prefix Python commands with `uv run`.

**Tests need a Postgres, never SQLite.** Start the throwaway test database first:
`docker compose up -d --wait db-test` (see `docker-compose.yml`; it listens on
`127.0.0.1:55432`, data lives on tmpfs, and `docker compose down` discards it). Dev
database: `docker compose up -d --wait db` (`127.0.0.1:15432`, volume `postgres_data`).
Neither uses 5432, which is often taken by a Postgres installed on the host. Never point
test runs at a developer's own database — `tests/conftest.py` refuses any database whose
name does not end in `_test`.

**Docker:** `Dockerfile` here builds a standalone production image (multi-stage,
`uv`-installed venv copied into a slim runtime image); its `CMD` runs `alembic
upgrade head` before starting `uvicorn`, so schema migrations are automatic on
every container start. It's normally run via the sibling `../docker-compose.yml`
(see `../DOCKER.md`), not built standalone — that compose file wires this
service to a Postgres container and to `genealogy-web`. `docker-compose.yml`
*in this directory* is the dev/test stack (`db`, `db-test`, `api`); the `api`
service also joins the fixed-name `genealogy_dev` network so
`../genealogy-web/docker-compose.yml` can call `http://api:8000`. The container
healthcheck hits `GET /health`.

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
walks the whole table in one query and reconstructs the tree in Python
(`_build_tree`, a dict keyed by `parent_id`, no recursive SQL), then
`_to_skeleton` strips it to `{id, name, children}` — the tree response is
deliberately just the shape, so it stays small for big families. Everything
else about a member comes from `GET /members/{id}` (`MemberDetail`: years,
gender, notes, avatar, profile fields, spouses, computed `sibling_rank`),
which the frontend fetches lazily, one request per member it needs.

**Profile fields (design: `docs/superpowers/specs/2026-10-17-member-profile-fields-design.md`)** —
`courtesy_name` (tên tự), `title` (chức vị), `residence`, `burial_place`,
`burial_latitude`/`burial_longitude` are nullable columns on `members`,
shared by `MemberCreate`/`MemberUpdate` through the `_ProfileFields` base in
`app/schemas/member.py`: strings are stripped and blank becomes `None`,
latitude/longitude are range-checked and **both-or-neither** (422
otherwise). `PUT /members/{id}` is a *full replacement*, so any of these
omitted in the body becomes `NULL` — clients must send every field.
`MemberDetail.sibling_rank` ("Trưởng/Thứ/Út nam|nữ") is **computed, not
stored** (`_sibling_rank` in `app/routers/member.py`): among same-parent,
same-gender siblings ordered by birth year (unknown last) then id; `None` for
roots and members without a male/female gender. Spouses (parent_id NULL) are
never siblings.

`PUT /members/{id}` prevents
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
Alembic specifically (see the import-order gotcha below,
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
(`@lru_cache`-wrapped) from `.env` / environment: `DATABASE_URL` — or, when it
is unset, `POSTGRES_HOST`/`POSTGRES_PORT`/`POSTGRES_USER`/`POSTGRES_PASSWORD`/
`POSTGRES_DB`, from which the URL is built with SQLAlchemy's `URL.create` so a
password containing `@ : / # ?` is percent-encoded instead of corrupting the
URL (the root `docker-compose.yml` uses this form; `DATABASE_URL` wins if both
are given) —
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

**Multi-family trees, roles and account status (designs: `docs/superpowers/specs/2026-10-17-roles-and-admin-design.md`
and `...-multi-tree-design.md`)** — one deployment hosts many families. `trees(id, name, slug)`;
`members.tree_id` is NOT NULL; `users.tree_id` is NULL **only for superadmins**; `site_settings` is per
tree (PK `(tree_id, key)`: `visibility` private/public, `registration` open/approval/closed). Roles:
`superadmin` (platform owner, no tree, acts in any tree), `admin` (one tree), `member` (reads one
tree); statuses `pending` | `active` | `disabled`. Constants and setting defaults: `app/core/roles.py`.
**Which tree a request acts on** (`app/core/tenancy.py`): a signed-in user → their own `tree_id`
(nothing the client sends can change that); a superadmin → `X-Tree-Id` header, else the lowest-id
tree; a guest / signup → the `tree_slug` cookie (set by the web app's `/t/<slug>` route), else the
only tree if there is exactly one. **Cross-tree ids always answer 404 (never 403), for reads and
writes alike** — keep it that way (`_member_in_tree` in `app/routers/member.py`; the admin router's
`_user_in_tree`). Every member route takes `get_read_context` (an active user, or a guest on a
public tree; guests with no resolvable tree get a plain 401 so the web app sends them to /login) or
`get_write_context` (admin/superadmin) from `app/core/permissions.py`; a new write route that
forgets the latter would be open to members, and `tests/test_multi_tree.py` /
`tests/test_roles_admin.py::test_members_can_read_but_not_write` are where to add it. **Bootstrap:**
the first registration while `users` is empty becomes the tree-less *superadmin* and a default tree
is created if none exists; everybody else joins the resolved tree as a `member` under *that tree's*
registration mode (400 when several trees exist and no cookie says which; 403 when closed).
`login` answers 403 `account_pending` / `account_disabled`, and `get_current_user` re-checks `status`
on every request, so disabling an account kills its token at once. Guests get a **redacted**
`MemberDetail` (no `notes`, `residence`, `burial_*`); `/uploads/*` (avatars) is still served
statically without auth (random UUID names only) — tighten before relying on private mode for photos.
Admin endpoints (`app/routers/admin.py`) act on the resolved tree only: `GET/POST /admin/users`,
`PATCH /admin/users/{id}` (role admin/member and status; **the last active admin of a tree can never be
demoted or disabled**, 409; superadmins are invisible to tree admins and `superadmin` can't be granted
here), `GET/PUT /admin/settings`; `GET /site/info` (public) describes the visitor's tree. Superadmin
web UI does not exist yet — **`scripts/manage.py`** (`app/cli.py`; `create-tree`, `rename-tree`,
`create-user` incl. superadmin, `set-role`, `list`) stands in for it, and `scripts/seed_members.py`
takes `--tree-slug`. The migrations turn every pre-existing user into an admin and move all existing
data into one `default` tree. Tests that need several people at once use the `make_client` fixture
(independent cookie jars); `tree` makes a tree for ORM-level tests.

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
`DateTime(timezone=True)`** — a leftover from when the tests ran on SQLite, which
silently drops tzinfo on round-trip (comparing against `datetime.now(timezone.utc)`
raised `TypeError`). The suite now runs on Postgres where either would work, but the
columns and `_utcnow()` stay naive-UTC end to end because changing them needs a
migration for no gain; keep every comparison naive-UTC. Tests never send real email — they monkeypatch
`app.routers.auth.send_password_reset_email` directly (see
`tests/test_password_reset.py`); the one test that exercises
`app/core/email.py` itself monkeypatches `smtplib.SMTP`.

**Import-order gotcha for SQLAlchemy metadata:** `Base.metadata` only knows
about models that have already been imported — SQLAlchemy registers a model at
class-definition time. The test schema is built by running the real Alembic
migrations (not `create_all`), so this matters for `alembic/env.py`'s import line
(see above); fixtures that touch ORM classes import them inside the test body.

**Global error handling:** `app/main.py` registers a catch-all
`@app.exception_handler(Exception)` that returns a generic 500 JSON body
instead of leaking stack traces; domain errors (duplicate email, bad
credentials, invalid token) are raised as `HTTPException` in the router
directly.

## Testing

Tests run against a real Postgres (the `db-test` service of `docker-compose.yml`, same
major version as the deploy). `tests/conftest.py`:
- `_database` (session scope, autouse) refuses a database not named `*_test`, drops and
  recreates the `public` schema, then runs `alembic upgrade head` **in a subprocess**
  (keeps alembic's logging config out of pytest) — so migrations are tested too, and the
  suite fails fast with instructions if the container isn't running. Override the target
  with `TEST_DATABASE_URL`.
- `_clean_tables` (autouse) runs `TRUNCATE ... RESTART IDENTITY CASCADE` on every table
  before each test, so ids start at 1 and tests are independent.
- `engine`/`session`/`client` use `NullPool`: asyncpg connections are bound to the event
  loop and pytest-asyncio gives each test its own loop, so connections can't be pooled
  across tests. `client` overrides `get_db` with sessions from that engine.
- `_env` (autouse) points `DATABASE_URL` at the test database and `UPLOAD_DIR` at a
  per-test `tmp_path` (also exposed as the `upload_dir` fixture), so tests never write
  into the repo's `uploads/`.

`asyncio_mode = "auto"` is set in `pyproject.toml`, so async test functions and fixtures
don't need `@pytest.mark.asyncio`. Foreign keys are enforced for real (no SQLite pragma
needed). Moving off SQLite already caught one real bug: `GET /members/tree` had no
`ORDER BY`, so Postgres reshuffled siblings after an edit (`tests/test_member_order.py`)
— keep list queries ordered.

`GET /health` (public, no DB access) is the container healthcheck target.
