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
- Seed a family tree from a `{name, children}` JSON file: `uv run python scripts/seed_members.py path/to/tree.json [--tree-slug SLUG]`
- Manage trees/users from the command line (the web page `/he-thong` covers the common cases; `set-role superadmin` is CLI-only): `uv run python scripts/manage.py --help`
- **Pointing the app at a throwaway database** (smoke runs): export `POSTGRES_HOST/PORT/USER/PASSWORD/DB` (or `DATABASE_URL`) in the shell — the environment beats `.env`. Still print the host/db from `get_settings().database_url` before starting anything. The dev `.env` (copy of `.env.example`) targets the compose `db` on `127.0.0.1:15432`: `docker compose up -d --wait db && uv run alembic upgrade head`.

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
plus a `Member` CRUD API. One deployment hosts **many families**: every member
belongs to a tree (`members.tree_id`), every user to one tree (or none, for the
superadmin), and every `/members/*` route acts on exactly one tree — see the
"Multi-family trees" section below and `docs/superpowers/specs/` for why.

**`Member` (`app/models/member.py`)** is a single self-referencing table:
`id`, `full_name`, `parent_id -> members.id` (nullable; `NULL` = root),
`birth_year`/`death_year` (nullable ints; GĐ2 added optional month/day and
calendar flags beside them — see "Profile data (GĐ2)"), `gender` (nullable, plain
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
walks the tree's members in one query and reconstructs the tree in Python
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
product decision to allow it. Access control is per route, not router-level:
reads use `get_read_context`, writes `get_write_context` (see "Multi-family
trees" below).

**Profile data (GĐ2; design: `docs/superpowers/specs/2026-10-17-gd2-profile-data-design.md`)** —
`members` also has `hometown`, `phone`, `email` (phone/email are **hidden from guests**), partial dates
(`birth_month`/`birth_day`/`death_month`/`death_day`, each optional and valid **without a year**, so a giỗ needs only a lunar
day+month) with calendar flags `birth_is_lunar` (default false), `death_is_lunar` (default **true**) and `*_leap_month`,
`birth_order` (manual sibling order), `is_adopted`, and `mother_id` (FK → `members.id`, `ON DELETE SET NULL`).
Validation lives in `_ProfileFields` (`app/schemas/member.py`): day needs month, lunar day ≤ 30, a real calendar date when
year+month+day are all solar, leap flag only on a lunar month, same-year death-before-birth rejected when both dates use the same
calendar, phone chars `0-9 + - ( ) . space`, email via `email_validator` (no deliverability check). **`mother_id` must be a
recorded spouse of the father** (`_check_mother`, 400) and requires `parent_id`, so changing the father forces the client to
send a new/empty mother. Ordering: siblings sort by `birth_order` (set first), then creation id in `/members/tree`; `sibling_rank`
uses `birth_order`, then birth year, then id; a member's spouses are listed by `marriage_year` (unknown last). Writes go through
`_assign` over `PROFILE_FIELDS` (shared by POST/PUT/PATCH/CSV) — **add a new column to `PROFILE_FIELDS`, the schemas, `MemberRead`/
`MemberDetail`, the CSV columns and the web `profileToPayload`** or PUT (a full replacement) will silently wipe it.

**Data-entry tools (`app/routers/member_tools.py`, admin-only, per tree; registered *before* `member.router` so
`/members/table` beats `/members/{id}`)** — `PATCH /members/{id}` (only the fields sent; merged onto the stored member and validated
as a `MemberUpdate`, `null` clears), `GET /members/table` (paged, depth-first order, filters `q`/`generation`/`under`/repeatable
`missing`; spouses are not rows), `GET /members/completeness`, `POST /members/{id}/split` (2–50 names; 409 if the member has children
or a spouse), `GET /members/export.csv` (UTF-8 + BOM) and `POST /members/import?dry_run=` (CSV: row with `id` updates, row
without creates a child; blank cell = unchanged, `-` clears/resets a flag; **all-or-nothing** with a per-row 422 error list; cycle,
duplicate-id, foreign-tree and mother checks happen in memory row by row; 5 MB / 10,000 rows).

**Search, branches and stats (GĐ3; design: `docs/superpowers/specs/2026-10-18-gd3-search-branches-design.md`)** —
`GET /members/search` (`app/routers/member_search.py`, registered before `member.router`) is a plain read that works on the
tree **loaded in memory** (`app/core/tree_layout.py`: `TreeLayout`/`load_layout` give depth-first order, generation, deepest
branch, spouses' partner), not SQL — no `unaccent`/`pg_trgm` extension is needed. `fold()` (`app/core/text.py`: NFD, drop
combining marks, `đ→d`, lower, single spaces) is applied to both sides, so `hòa` = `hoà` = `hoa`; every query word must occur in
the name, rank is exact > prefix > word-prefix > contains; spouses are searched only when `q` is given and report `spouse_of`;
when a text query finds nothing, difflib-close names (≥ 0.6, one per distinct name) come back as `suggestions`. Filters:
`generation`, `branch` (the head's whole subtree), `born_from/to`, `hometown`, `gender` (incl. `unknown`), `status`
(same living/deceased/unknown rule as the web app: `member_status`). `GET /stats` (+ optional `branch`) gives counts per
generation/gender/status/branch. **Branches** (`app/models/branch.py`, `app/routers/branches.py`): a branch = the subtree below
`root_member_id` (UNIQUE: a person heads at most one, 409; `ON DELETE CASCADE` so deleting a childless head removes its branch);
a member's branch is the **deepest** head among themselves and their ancestors — nothing is stored per member
(`deepest_branch` for one member, `TreeLayout.branch_of` for the whole tree; spouses take their partner's). `GET /branches` is a
read (counts = whole subtree, sub-branches included), writes are admin-only, another tree's head/branch is 404;
`MemberDetail.branch` carries `{id, name, color}`. Revisit the in-memory approach (add a SQL index) only if a tree passes
~10,000 people.

**Change requests and audit log (GĐ4; design: `docs/superpowers/specs/2026-10-18-gd4-change-requests-design.md`)** —
members never write to `/members/*`; they **propose** through `/requests` (`app/routers/requests.py`, `get_user_context` = any signed-in
user) and an admin approves. Kinds: `edit` (fields in `PROPOSABLE` = writable fields minus `parent_id`/`mother_id`), `add_child`,
`report` (text only, min 5 chars). A proposal is validated like `PATCH`/`POST` (merged onto the current data through
`MemberUpdate`/`MemberCreate`), stored as the **minimal, normalised** `changes` plus `base` (the person's values then), and a no-op is a
422. `GET /requests` shows admins every request of the tree and everybody else only their own (another tree's or someone else's is 404);
`/requests/summary` is the sidebar badge count. Approve applies the change through the **same code as a direct edit**
(`_apply_update(..., commit=False)` / `add_member`), so every validation and the audit entry apply, then closes the request in the same
transaction; any failure (person deleted, data no longer valid) rolls back and answers 409 leaving it pending. Reject needs a note; decided
requests are 409; only the requester cancels (404 for others). `diff` is computed on read and flags `stale` when a pending request's
fields changed since `base`. Emails (`send_email`, `_notify`) go to the tree's active admins on arrival and to the requester on a decision,
only when `SMTP_HOST` is set, and **never block or fail the action**. The **audit log** (`app/core/audit.py`, `audit_log` table, read by
`GET /audit`, admin only) is written by `audit_member`/`audit.record` **in the caller's transaction** for member
create/update/delete/split/avatar, marriage create/update, CSV import (one entry per changed person), branch create/update/delete and
request decisions; `member_id` has no FK so a deleted person's history survives, creation/deletion entries list only non-default fields.
**Any new write route must call `audit_member`/`audit.record`** (and be added to the admin-only list in the role tests).

**Lunar calendar, giỗ, events, .ics and reminders (GĐ5; design: `docs/superpowers/specs/2026-10-18-gd5-calendar-design.md`)** —
`app/core/lunar.py` is Hồ Ngọc Đức's astronomical algorithm with the **UTC+7 meridian** (no lookup table: the Chinese calendar uses UTC+8
and differs in some years). **`math.floor`, not `int()`, in `_sun_longitude`** — `T` is negative before 2000 and truncation toward zero
silently broke 1990. Tested against Tết 1975–2027, Trung thu, Giỗ Tổ, leap months and a 50-year day-by-day round trip
(`tests/test_lunar.py`). **Giỗ are computed, never stored** (`app/core/calendar_items.py`): a lunar death date as entered, a solar one
only with a full date (converted once; month+day without a year cannot be, and is counted in `incomplete`); every lunar year **after**
the death year gets one (`years` = giỗ lần thứ N, `None` without a death year); a leap-month death uses the regular month; day 30 in a
29-day month is day 29. `events` (admin CRUD, audited as `event.*`) are rules expanded over a range: solar or lunar, one-off (needs
`year`) or yearly (`year` = optional start). **Routers register `calendar_items.vn_today()` through the module** (`calendar_items.vn_today()`,
not `from … import vn_today`) so tests can patch "today"; Vietnam's date is UTC+7. `/calendar/month|upcoming|convert` are plain reads;
**`/calendar/feed/<token>.ics` is public by design** (a phone calendar sends no cookie): `trees.calendar_token` is the secret, admins
create/regenerate (`POST`, which cuts off old subscribers) or remove (`DELETE`) it, any signed-in user of the tree reads it
(`GET /calendar/subscription`). `app/core/ics.py` writes the feed (CRLF, 75-octet folding at character boundaries, escaped text, all-day
events, stable UIDs, 30 days back to 2 years ahead). **Reminders:** per user `reminder_days` (subset of 0,1,3,7,14,30; default "7,1") and
`reminder_email` (`GET/PUT /calendar/reminders`); `app/jobs/reminders.py::send_due_reminders` creates `notifications` rows with
`INSERT … ON CONFLICT DO NOTHING` on `(user_id, dedupe_key)` — **idempotent**, so the hourly worker (`scripts/run_reminders.py --interval
3600`, the `worker` service in the root compose) can restart or overlap without duplicates — and emails only when `SMTP_HOST` is set
(a failing mail server costs the email, never the notification). `GET /notifications`, `POST /notifications/read` (only my own rows).

**Media and places (GĐ6; design: `docs/superpowers/specs/2026-10-18-gd6-media-places-design.md`)** —
**`media`** (`app/routers/media.py`, `app/core/media_processing.py`, `app/core/media_files.py`): photos and PDFs on a person
(`/members/{id}/media`) or a place (`/places/{id}/media`), admin upload (≤ 10 MB), files under `UPLOAD_DIR/media/` + `media/thumbs/` with random
UUID names. **The content is checked, not the declared type**: an image must open in Pillow (JPEG/PNG/WebP; decompression-bomb limit of 60 M
pixels; EXIF rotation applied to the 480 px JPEG thumbnail only, the original is stored untouched), a PDF must start with `%PDF-`; the check
runs in `asyncio.to_thread`. Files are served by `GET /uploads/media/<name>` and `/uploads/media/thumbs/<name>` (`app/routers/uploads.py`) with
`can_read_tree(..., allow_guests=False)` — **signed-in users of the tree only, never guests of a public tree** (scans of documents and graves;
per-item privacy is GĐ11); everything else is 404. Deleting a person or place deletes their files (after the commit succeeds). Uploads, captions and
deletions are audited (`media.*`). **`places`** (`app/routers/places.py`): kinds `clan_house|temple|tomb|cemetery|other`, GPS both-or-neither,
**signed-in readers only** (a grave's location is burial information, which `MemberDetail` already redacts for guests), admin writes
(audited `place.*`). Members point at one with `burial_place_id` (FK `SET NULL`) + `burial_plot`, checked to be the same tree (`check_place`, 404);
both are in `PROFILE_FIELDS`, the CSV columns and the redaction list, and are **not proposable** (`PROPOSABLE` excludes them).
`MemberDetail.resting_place` carries the place's name/kind/GPS. `POST /places/migrate-burials?dry_run=` groups the legacy `burial_place` text
(folded: case, diacritics, spacing), reuses a same-named place or creates a `tomb`, takes GPS from the first person who has it, links people
and leaves the old fields alone; idempotent. Events can have a `place_id` (calendar items then show the place as their location).
Pillow was added with `uv add pillow` (the Dockerfile installs from `uv.lock`, so the lock must be updated with the dependency).

**Chronicles (GĐ7; design: `docs/superpowers/specs/2026-10-19-gd7-chronicles-design.md`)** — `articles` (`app/routers/articles.py`): Markdown `body`
(≤ 100,000 chars), `kind` origin|lineage|precepts|event|person|other, `status` draft|published, `pinned`, `position`, `cover_media_id`; the slug is made
from the title (`make_slug`: folded, hyphenated, `-2`/`-3` on a clash, `bai-viet` when nothing is left) and **never changes after creation**, so links
survive renames. **Readers:** members and guests of a public tree see published articles only; drafts (and `GET /members/{id}/articles` drafts) are
admin-only; another tree is 404. `article_members` holds the people an article mentions, chosen by the admin (nothing is parsed from the text; ids of
another tree → 404). Article photos are `media` rows with `article_id` (`/articles/{id}/media`, same rules as GĐ6: admin upload, signed-in viewers
only); **a cover must be one of the article's own images** (`_check_cover`), and `articles.cover_media_id`/`media.article_id` reference each other, so
the cover FK is created with `use_alter` / in the migration after both tables exist. `POST /articles/reorder` sets `position`; the list order is
pinned, position, newest. `timeline_entries` (`/timeline`: year 1–2200, optional month/day, a day needs its month and must exist, optional person and
article; listed by date with undated parts first) and `generation_words` (`PUT /generation-poem` replaces the whole bài đệm, one word per generation, ≤ 200)
are read like articles and written by admins; every write is audited (`article.*`, `timeline.*`, `poem.update`).

**Statistics overview (GĐ8; design: `docs/superpowers/specs/2026-10-19-gd8-statistics-design.md`)** — `GET /stats/overview`
(`app/routers/member_search.py`, `app/core/overview.py::compute_overview`, a pure function of a `TreeLayout`) over **blood members** (spouses are counted
once, separately): totals and the living/deceased/unknown rule, gender (also per generation), per branch, **lifespan** (deceased with both years and an age of
0–120, so a typo like a 200-year life is ignored; mean/median/min/max, by gender), birth decades, children (parents, average per parent, childless, the person with
most children — ties go to the lowest id), the **longest line** (the first deepest person in tree order and the chain of names up to the root), the commonest
middle names (the word after the surname, names of 3+ words) and given names (last word) — **counted with accents folded and shown in the commonest spelling**
— and `completeness` (`have/total` for gender, birth year, birth day+month, hometown, residence, avatar, any photo). Aggregates only, so guests of a public
tree may read it. `/members/table?missing=` gained `avatar`.

**Invitation cards and RSVPs (GĐ9; design: `docs/superpowers/specs/2026-10-19-gd9-invitations-design.md`)** — `event_cards` = an invitation for ONE occurrence of an
event (`date` must be an occurrence: `calendar_items.event_items([event], d, d)` non-empty, else 422), with a secret `token` (`secrets.token_urlsafe(24)`),
`message`, `closes_on` and a manual `closed`; `event_rsvps` = one guest's answer (`response` NULL = invited, silent) with its own `invitee_token`. Admin routes
(`/events/{id}/cards`, `/cards/{id}`, `/invitees`, `/responses/{id}`, `/export.csv`; admin-only, tree-scoped, audited as `card.*`) and **public routes
(`app/routers/invitations.py::public_router`, `/invitations/{token}`) that need no login and no tree cookie — the token is the access control**. The public
view returns the event, solar + lunar date, the chosen place's name/address/GPS, the message and **totals only (never other guests' names or notes)**; the
open link's `respond` creates a guest (a name is required) and returns that guest's personal token, a personal link updates its own row and **keeps what the guest
did not send again** (`model_fields_set`: an omitted note/party size survives, an explicit null clears the note). A closed card or a passed deadline
(`calendar_items.vn_today()`, patchable in tests) is 409 for answers but still viewable; a card takes at most `MAX_RESPONSES` (500) answers. Unknown tokens are
404. Deleting the event or the card removes the links.

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
served back by `GET /uploads/avatars/{filename}` (`app/routers/uploads.py`, **not** a
static mount: it looks up which member owns the file and answers only people who may read that
member's tree — see "Multi-family trees"; everything else is a plain 404) —
`avatar_url` in the DB is always a path like
`/uploads/avatars/<uuid>.jpg`, never an absolute URL with a host.
`POST /members/{id}/avatar` (multipart, field `file`) validates content
type (`image/jpeg`/`png`/`webp` only) and size (5 MB max), deletes the
member's previous avatar file if one existed, writes the new one under
a random UUID filename, and updates `avatar_url`; `DELETE
/members/{id}/avatar` removes the file and clears the column. Only
top-level tree members get avatars — `SpouseInfo` has no `avatar_url`
field. **`app/main.py` still creates `<upload_dir>/avatars/` at import time**
(`Path(settings.upload_dir, "avatars").mkdir(parents=True,
exist_ok=True)`) so the first upload never fails on a missing directory. Speaking of which: **`tests/conftest.py`'s
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
(`@lru_cache`-wrapped) from `.env` / environment: `POSTGRES_HOST`/`POSTGRES_PORT`/
`POSTGRES_USER`/`POSTGRES_PASSWORD`/`POSTGRES_DB`, from which the URL is built with
SQLAlchemy's `URL.create` so a password containing `@ : / # ?` is percent-encoded
instead of corrupting the URL — the **same names in `.env.example`, this
directory's `docker-compose.yml` and the root `docker-compose.yml`**. A full
`DATABASE_URL` is still accepted as an override. **Precedence: the process
environment beats the `.env` file, whichever form each uses** (so a leftover
`DATABASE_URL` in `.env` cannot hijack a run that sets `POSTGRES_*`, and the test
suite's `DATABASE_URL` cannot be overridden by a developer's `.env`; within one
layer `DATABASE_URL` wins) —
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
(nothing the client sends can change that); a superadmin → `X-Tree-Id` header, else the `acting_tree` cookie (set by the web
tree switcher; garbage or an unknown id is ignored, while a wrong *header* is a 404), else the lowest-id
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
`MemberDetail` (no `notes`, `residence`, `burial_*`, `phone`, `email`). **Avatar files follow the same rule**
(`can_read_tree` in `app/core/permissions.py`: an active member of the owning tree, the superadmin, or anyone
when that tree is public; a disabled/pending account or a bad token counts as a stranger; unknown, orphaned
or malformed names and other trees' files all answer 404; `Cache-Control: private`). **Platform endpoints**
(`app/routers/trees.py`, `require_superadmin`): `GET /trees` (counts, admins, `is_current`), `POST /trees`
(a tree *and* its first admin, all-or-nothing; the generated password is returned once), `PATCH /trees/{id}`
(name/slug).
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

**Book PDF (GĐ10; design: `docs/superpowers/specs/2026-10-19-gd10-export-design.md`)** — `GET /book.pdf` (`app/routers/book.py`, admin-only via `get_write_context`, tree-scoped,
audited as `book.export`) renders a printable "quyển phả" with ReportLab (`app/core/book.py::build_book`, **synchronous, run through `asyncio.to_thread`**): cover, a
table of contents with real page numbers (`multiBuild` + `afterFlowable` notify), chronicles (**published articles only; drafts never**, tộc ước first, bài đệm,
timeline), "Phả hệ theo đời" (a block per person), and "Phả đồ" — vector diagrams drawn on landscape A3 pages, **split by depth (≤4) and leaf count (≤14)** with
"▼ xem tiếp" markers; small branches share a page (`KeepTogether`). Options (query): `chronicles`, `profiles`, `diagram`, `notes`, `photos` (default false),
`contacts` (**default false: phone/email are never printed unless asked**), `max_generation`. Fonts are the DejaVu TTFs vendored in `app/assets/fonts/` (they cover
Vietnamese; the book never depends on host fonts). Markdown is reduced to bold/lists/quotes/rules with every piece of text XML-escaped (`&` in a title is the classic
ReportLab crash). `pypdf` (dev) reads the PDFs back in `tests/test_book.py`. A ~700-person tree builds in well under the 90 s the test allows.

**Privacy per field (GĐ11; design: `docs/superpowers/specs/2026-10-19-gd11-privacy-ops-design.md`)** — `app/core/privacy.py` is the ONE place that decides who sees
`phone/email/residence/notes/burial/avatar/hometown` (levels `admin < member < public`; stored as `site_settings` rows `privacy.<field>`; defaults reproduce the pre-GĐ11
behaviour: members see all, guests of a public tree see hometown + avatar). `GET/PUT /admin/privacy` (audited `privacy.update`). Applied in the member detail
(**including the spouses' notes**), the **avatar file route** (`read_access` in `permissions.py` returns the user so the file obeys the same rule as the URL) and change
requests (a member cannot *propose* a field closed to them; closed fields' old values are removed from what they read). Any new endpoint that returns member fields to
non-admins must go through `privacy_for` — do not re-implement "guests get less" by hand.

**Kinship (GĐ11 B4)** — `GET /members/relationship?a=&b=` (`app/core/kinship.py::relate`, pure over `TreeLayout`): father-line terms only (`bác` = older than the father,
`chú/cô` younger, cousins ordered by **branch order not age**, `ông/cụ/kỵ`, `chắt/chút`), spouses through their partner with the usual terms (thím, chị dâu, dượng...). Maternal
relatives and in-law terms beyond a short table are out of scope — the mother is a spouse, not a parent, so `cậu/dì` cannot be derived.

**Operations (GĐ11)** — `app/core/rate_limit.py` (in-memory sliding windows, per process): login 20/5 min per address + **8 failures/5 min per account**, register 10/h, forgot-password 5/h,
public RSVP 40/10 min; 429 + `Retry-After`. **Measured:** Next.js's `/api` proxy does not forward the visitor's address, so unless `TRUSTED_PROXY_HOPS` says a real reverse proxy
overwrites `X-Forwarded-For` the "address" is the web container for everybody and the per-address limits are loosened ×5 (`SHARED_ADDRESS_FACTOR`). Tests switch the limiter off in
`conftest.py` (`limiter.enabled`) — turn it on with the `on` fixture in `tests/test_rate_limit.py`. Security headers come from a middleware in `app/main.py`. `GET /export/data.json` (admin, audited
`data.export`) dumps the tree's tables **without credentials or tokens** (`SECRET_COLUMNS`). Backups are `scripts/backup.sh` / `scripts/restore.sh` at the repo root (see `docs/SAO-LUU.md`).

**Admin console (design: `docs/superpowers/specs/2026-10-18-admin-console-design.md`, plan: `docs/superpowers/plans/2026-10-18-admin-console.md`)** — `GET /admin/overview`
(`app/core/admin_overview.py::compute_overview`) is the admin home's "Cần làm" list: items `{key,count,text,href,kind task|notice}` with zero-count tasks left out; later phases
append items to the same function. Every admin endpoint is tree-scoped through `get_write_context`.

**Admin users (admin console phase 2)** — `users.last_login_at` (set on every successful login; NULL for accounts that never logged in *since the column existed*, so the UI says "Chưa ghi nhận")
and `users.member_id` (optional display link to a person of the same tree, unique, `ON DELETE SET NULL`). `GET /admin/users?q=&status=&role=` (q folded over name + email),
`POST /admin/users/approve {ids}` (only this tree's `pending` users; anything else is silently skipped), `POST /admin/users/{id}/password` (admin sets or generates a password, returned **once**,
never audited/logged; superadmins and other trees' users are 404), `PATCH /admin/users/{id}` also takes `member_id` (`model_fields_set`: omitted = unchanged, `null` = unlink; other tree's person 404, already-linked person 409).
All of them write `audit_log` (`user.create|update|approve|password_reset`). **`TRUNCATE members … CASCADE` now also empties `users`** (FK) — test/smoke resets must keep a copy of the users they need.

`GET /health` (public, no DB access) is the container healthcheck target.
