# Superadmin console Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn `/he-thong` into the platform owner's console: attention list, family life cycle (pause/resume/delete), admins of a family, a platform log, and server health.

**Architecture:** New `/platform/*` backend router plus extensions of `/trees`, all behind `require_superadmin` and independent of the acting tree. A separate `platform_events` table is the superadmin's log. A paused family is enforced at the few doors that resolve a tree or a user. The web gets a route group `/he-thong/*` reusing the admin console's frame/tiles/dialog conventions.

**Tech Stack:** FastAPI/SQLAlchemy async/Alembic/pytest (db-test), Next.js 15/React 19/Tailwind v4 tokens, vitest, Playwright on the throwaway stack.

**Spec:** `docs/superpowers/specs/2026-10-18-superadmin-console-design.md` (binding; its "Calls made" are decided).

## Global Constraints

- Every platform endpoint depends on `require_superadmin` (members/admins 403, guests 401) and must not depend on the acting tree.
- Every platform write calls `app/core/platform_log.py::record` in the same transaction; no passwords, tokens or hashes in responses (except a one-time password), logs or log rows.
- Dangerous actions (pause, resume, delete, admin password reset, disabling an admin) ask first in the UI; delete additionally needs the slug typed.
- A family always keeps one active admin through this console; superadmin accounts are never addressable here; granting `superadmin` stays CLI-only.
- UI: body ≥ 16px (hints ≥ 14px), targets ≥ 44px, visible focus, contrast ≥ 4.5:1 on heritage/warm/modern/elegant, status chips = coloured border + `text-default`, links on page background `text-default` + underline, tables → cards on a phone, no horizontal scroll at 375px; dialogs use `useDialogFocus`/`ConfirmDialog`.
- Vietnamese UI; pages take no props; vitest imports in `src/lib` are relative.
- Never touch the host Postgres (5432) or the developer's `genealogy` DB; tests on `db-test`; smoke on the throwaway container (`reset.sh` keeps a copy of users because `TRUNCATE members … CASCADE` empties `users`).
- Nothing is pushed; commits end with `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.

## Review Focus

- A paused family is really stopped: login (403 `tree_paused`), existing JWTs of its users on the next request, guest/signup resolution, the public `.ics` feed, public invitation pages, avatar/media for guests, and the reminder worker — and **resume restores all of it** (tests in Tasks 4).
- Delete: refuses an active tree and a wrong slug; removes every table's rows for that tree and the files; leaves other trees untouched; survives FK order and a missing file (Task 5).
- A family can never be left without an active admin via this console, including disabling the last one and pausing/resuming interplay; superadmins and other trees' users are not addressable (Task 7).
- No password or token appears in any platform-log row or response except the one-time password (Tasks 3/7).
- The acting-tree cookie pointing at a deleted or paused tree falls back instead of erroring for the superadmin (Task 5).

---

## Phase 1 — Frame, overview, log foundation

### Task 1: `platform_events`, overview, last activity (API)

**Files:**
- Create: `alembic/versions/b4e6f0a38d59_platform_events.py` (down_revision `a3d5e9f27c48`), `app/models/platform_event.py`, `app/core/platform_log.py`, `app/schemas/platform.py`, `app/routers/platform.py`, `tests/test_platform_overview.py`
- Modify: `app/main.py` (register router), `alembic/env.py` (import the model), `app/routers/trees.py` (log create/rename; `last_activity` in `TreeRead`), `app/schemas/tree.py`

**Interfaces:**
- Produces: table `platform_events(id PK, actor_id INT NULL REFERENCES users ON DELETE SET NULL, actor_name VARCHAR(255) NOT NULL, action VARCHAR(40) NOT NULL, tree_id INT NULL (no FK), tree_name VARCHAR(255) NULL, details JSONB NULL, created_at TIMESTAMPTZ default now)`, index on `created_at`.
- Produces: `def record(db: AsyncSession, *, actor: User, action: str, tree: Tree | None = None, tree_id: int | None = None, tree_name: str | None = None, details: dict | None = None) -> None` in `platform_log.py` (adds a row; caller commits; `tree` fills id and name).
- Produces: `TodoItem`/`Overview` reused from `app/schemas/admin_overview.py`; `class PlatformOverview(BaseModel): items: list[TodoItem]; numbers: dict[str, int]` with keys `trees`, `trees_paused`, `members`, `users`, `media_bytes`; `async def compute_platform_overview(db) -> PlatformOverview` in `app/core/platform_overview.py`; `GET /platform/overview`.
- Produces: `TreeRead.last_activity: datetime | None` = max of the tree's `audit_log.created_at` and its users' `last_login_at`.

- [ ] **Step 1: Failing tests** (`tests/test_platform_overview.py`; fixture: two trees, `root` superadmin, `admin_a`, `member_a`, `admin_b`): `test_numbers_count_everything_across_trees`; `test_a_tree_without_an_active_admin_is_a_task` (disable `admin_b` through the DB → item key `trees_without_admin`, count 1, text "1 họ không có quản trị viên đang hoạt động", href `/he-thong/ho?loc=khong-admin`); `test_no_task_when_every_tree_has_an_active_admin`; `test_tree_create_and_rename_write_platform_events` (POST /trees, PATCH /trees/{id} → rows `tree.create`, `tree.update` with `tree_name`, and `details` without any password); `test_last_activity_is_the_latest_of_audit_and_login`; `test_only_the_superadmin_may_read` (admin 403, member 403, guest 401).
- [ ] **Step 2: Run** `.venv/bin/pytest tests/test_platform_overview.py -q` → FAIL.
- [ ] **Step 3: Implement** model + migration + `record` + overview + router + `last_activity` (one grouped query each, no N+1); log `tree.create` (details `{slug, admin_email}`) and `tree.update` (`{changes}` via `audit.diff_values`).
- [ ] **Step 4: Run** the file plus `tests/test_superadmin_trees.py tests/test_multi_tree.py` → PASS. **Step 5: Commit** `feat(platform): platform log table, overview, last activity`.

### Task 2: Console frame, home and the moved list (web)

**Files:**
- Create: `src/lib/platform/sections.ts`, `src/lib/platform/sections.test.ts`, `src/components/platform/PlatformFrame.tsx`, `src/components/platform/PlatformHome.tsx`, `src/app/he-thong/ho/page.tsx`
- Modify: `src/app/he-thong/page.tsx` (becomes the home), `src/components/platform/TreesPanel.tsx` (unchanged behaviour, loses its page chrome), `src/lib/platform/trees.ts` (`last_activity`, later `status`)

**Interfaces:**
- Produces: `PLATFORM_SECTIONS: {id,href,label,hint,icon,ready}[]` with ids `trees` (`/he-thong/ho`), `audit` (`/he-thong/nhat-ky`), `system` (`/he-thong/he-thong`) and `visiblePlatformSections()`; `AdminIcon` keys reused (add `platform`/`system` keys to `AdminIcon.tsx` if none fits); `PlatformFrame({title?, children})` = superadmin guard + `AppShell active="platform"` + "← Các họ nền tảng" + desktop section list; `PlatformHome` fetches `/api/platform/overview`.

- [ ] **Step 1: Failing test** `sections.test.ts`: only `ready` sections are visible (initially `['trees']`), hrefs unique and all under `/he-thong`.
- [ ] **Step 2–3:** implement; the old page content moves to `/he-thong/ho` under `PlatformFrame title="Các họ"`; home = to-do box ("Không có việc nào cần làm" when empty), the four numbers (họ, người, tài khoản, dung lượng ảnh via `formatBytes` from `lib/admin/backup.ts`), tiles, no log strip yet.
- [ ] **Step 4:** `npx vitest run && npx tsc --noEmit && npm run lint`. **Step 5: Commit.**

### Task 3 (ship Phase 1)
- [ ] Playwright `gd14-p1.mjs` (superadmin on the throwaway stack, phone + desktop): home numbers, create a family at `/he-thong/ho` still works and shows in the numbers, an admin disabled through the API produces the "không có quản trị viên" task, admin/member are sent away from `/he-thong`. Docs (both `CLAUDE.md`, roadmap line), full suites, build (stop `next dev` first), `finish.sh`.

---

## Phase 2 — Family life cycle

### Task 4: `trees.status`, pause/resume and enforcement (API)

**Files:**
- Create: `alembic/versions/c5f7a1b49e60_tree_status.py` (down `b4e6f0a38d59`), `tests/test_tree_pause.py`
- Modify: `app/models/tree.py`, `app/routers/trees.py`, `app/routers/auth.py` (login + `get_current_user`), `app/core/tenancy.py` (`public_tree`), `app/core/permissions.py` (`read_access`), `app/routers/invitations.py` (public routes), `app/routers/calendar.py` (feed), `app/jobs/reminders.py`, `app/schemas/tree.py` (`status`), `app/core/platform_overview.py` (item `trees_paused`)

**Interfaces:**
- Produces: `trees.status VARCHAR(10) NOT NULL DEFAULT 'active'` (`active|paused`); `Tree.is_paused` property; `POST /trees/{id}/pause` and `/resume` → `TreeRead` (idempotent: pausing a paused tree is 409); platform events `tree.pause`, `tree.resume`; overview task `trees_paused` (count of paused families, text "N họ đang tạm ngưng", href `/he-thong/ho?loc=tam-ngung`).
- Enforcement rules: a non-superadmin user of a paused tree gets **403 `tree_paused`** at login and in `get_current_user`; `public_tree` for a paused tree is 404; `read_access`/`can_read_tree` is False for guests of a paused tree (members/superadmin keep the existing rule except members of a paused tree, which `get_current_user` already refuses); public invitation routes and the `.ics` feed of a paused tree are 404; `send_due_reminders` skips paused trees. The superadmin still resolves, reads and acts on a paused tree.

- [ ] **Step 1: Failing tests** (`tests/test_tree_pause.py`): after `POST /trees/{id}/pause` — login of `admin_a`/`member_a` → 403 `tree_paused`; an already-logged-in `member_a` client's next `GET /members/tree` → 403; guest with `tree_slug` cookie on a public paused tree → 404/401 per existing guest rules (assert not 200); `.ics` feed 404; public invitation page 404 and respond 404; guest avatar 404; reminders job creates no notification for the paused tree (patch `vn_today`, as `tests/test_calendar_feed_reminders.py` does); the superadmin can still `GET /trees` and act on it (`X-Tree-Id`); `POST /trees/{id}/resume` restores **every** one of the above; pause twice → 409; unknown id → 404; non-superadmin → 403; both actions write `tree.pause|resume` events.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement** the rules above (a small `ensure_tree_active(tree)` helper in `app/core/tenancy.py` returning/raising consistently). **Step 4:** run the file plus `tests/test_auth.py tests/test_multi_tree.py tests/test_invitations.py tests/test_calendar_feed_reminders.py tests/test_uploads_access.py` → PASS. **Step 5: Commit.**

### Task 5: Delete a paused family (API)

**Files:** Create `app/core/tree_removal.py`, `tests/test_tree_delete.py`; modify `app/routers/trees.py`.

**Interfaces:**
- Produces: `async def delete_tree_data(db: AsyncSession, tree: Tree) -> dict[str, int]` (deletes rows in FK-safe order inside the caller's transaction and returns counts `{members, users, media, ...}`; returns the file names to remove via a second return or an attribute — design left to the builder but the router must remove files only **after** the commit succeeds); `class TreeDelete(BaseModel): slug: str`; `DELETE /trees/{id}` (body `TreeDelete`) → 204.
- Rules: 409 `tree must be paused first`; 422/409 when `slug` differs; platform event `tree.delete` with `tree_id`, `tree_name`, and `details {slug, members, users, media, files}` written before the delete commits; avatars (`UPLOAD_DIR/avatars/…`) and media files (+ thumbs) of the tree are removed, a missing file is ignored; other trees' rows and files untouched.

- [ ] **Step 1: Failing tests:** active tree → 409; wrong slug → refused; paused + right slug → 204, then `GET /trees` no longer lists it, every table has no row with that `tree_id` (query each table that has `tree_id`), its members/users/media rows gone, the files gone from a tmp `UPLOAD_DIR` (create an avatar and a media file first), a second tree with data and files is intact, the platform event exists with counts and no secrets; deleting while the superadmin's `acting_tree` cookie points at it → the next `GET /trees` still works (falls back); non-superadmin 403; unknown 404.
- [ ] **Step 2–4:** implement and run these plus `tests/test_platform_overview.py tests/test_tree_pause.py`. **Step 5: Commit.**

### Task 6: Pause/resume/delete UI (web) and ship Phase 2

**Files:** Create `src/components/platform/TreeActions.tsx` (+ `DeleteTreeDialog`), `src/lib/platform/lifecycle.ts`, `src/lib/platform/lifecycle.test.ts`; modify `TreesPanel.tsx`, `src/lib/platform/trees.ts` (`status`, `last_activity`), `sections.ts` home badge key for `trees_paused`.

**Interfaces:**
- Produces in `lifecycle.ts`: `statusLabel(status): 'Đang hoạt động' | 'Đã tạm ngưng'`; `lastActivityLabel(iso | null, now: Date): string` (reuse the admin `lastLoginLabel` wording: "Chưa có hoạt động" for null); `canDelete(tree: {status: string}, typed: string, slug: string): boolean` (paused and `typed.trim() === slug`); `deleteSummary(tree): string` (people, accounts counts sentence).

- [ ] **Step 1: Failing tests** for the four helpers. **Step 2–4:** the family card shows a status chip (border + default text), last activity, "Tạm ngưng"/"Kích hoạt lại" behind `ConfirmDialog`, "Xoá họ" only on paused families opening `DeleteTreeDialog` (lists what goes, link "Tải dữ liệu JSON trước" that sets the acting-tree cookie and opens `/api/export/data.json` in a new tab, slug input; the confirm button disabled until `canDelete`); filter chips from `?loc=` (`khong-admin`, `tam-ngung`); success/failure messages.
- [ ] **Ship:** Playwright `gd14-p2.mjs` (a member of a paused family cannot log in and the message is shown; resume restores login; delete flow end to end incl. typed slug, files gone via the API, the acting-tree switcher survives), docs, suites (stop dev server before build), `finish.sh`.

---

## Phase 3 — Admins of a family

### Task 7: Admins API and `set-password` CLI

**Files:** Create `tests/test_tree_admins.py`, `tests/test_cli_set_password.py`; modify `app/routers/trees.py`, `app/schemas/tree.py`, `app/cli.py`.

**Interfaces:**
- Produces: `GET /trees/{id}/admins -> list[TreeAdminRead]` (id, email, full_name, status, last_login_at); `POST /trees/{id}/admins` body `{email, full_name, password?}` → `TreeAdminCreated {admin, password | null}` (409 when the email exists anywhere) **or** body `{user_id}` to promote one of the tree's own users (role `admin`, status `active`); `PATCH /trees/{id}/admins/{user_id}` body `{status: "active"|"disabled"}`; `POST /trees/{id}/admins/{user_id}/password` body `{password?}` → `{password}`; CLI `manage.py set-password --email E [--password P]` (generates and prints when omitted; works for any user including superadmin).
- Rules: disabling the last active admin → 409; superadmins and other trees' users → 404; platform events `admin.create|promote|update|password_reset` with the email only.

- [ ] **Step 1: Failing tests** for each rule above, the one-time password logging check (`not in str(events)`), the CLI (run `app.cli.main([...])` and log in with the printed/given password).
- [ ] **Step 2–4:** implement; run with `tests/test_roles_admin.py tests/test_superadmin_trees.py`. **Step 5: Commit.**

### Task 8: Admins dialog (web) and ship Phase 3
- [ ] `AdminsDialog.tsx` from the family card: list (name, email, status, last login via `lastLoginLabel`), add new (generated or typed password, shown once with copy), promote (picker of the tree's other users), disable/enable behind `ConfirmDialog`, reset password dialog (reuse the one-time-password display pattern of `PasswordDialog`); tests for any new helper; Playwright `gd14-p3.mjs` (add an admin who can then log in, reset password works, last admin cannot be disabled → message); docs; suites; `finish.sh`.

---

## Phase 4 — Going in to help, platform log page

### Task 9: `support.enter`, events API, log page (API + web) and ship Phase 4

**Files:** Create `app/schemas/platform.py` additions, `tests/test_platform_events.py`, `src/app/he-thong/nhat-ky/page.tsx`, `src/components/platform/PlatformLogView.tsx`, `src/lib/platform/log.ts`, `src/lib/platform/log.test.ts`; modify `app/routers/trees.py` or `platform.py`, `src/components/platform/TreesPanel.tsx`, `src/components/layout/TreeSwitcher.tsx`, `sections.ts`, `PlatformHome.tsx`.

**Interfaces:**
- Produces: `POST /trees/{id}/support` → 204 (records `support.enter` with `tree_id`, `tree_name`); `GET /platform/events?action=&tree_id=&since=&until=&limit=&offset=` → `{total, items: [{id, action, actor_name, tree_id, tree_name, details, created_at}]}` newest first, dates are whole days in Vietnam time like `/audit`; unknown `action` prefix value is not validated (free text prefix filter).
- Produces in `log.ts`: `platformActionLabel(action): string` for `tree.create|update|pause|resume|delete`, `admin.create|promote|update|password_reset`, `support.enter`; `buildEventsQuery(filters, offset, limit?)`.

- [ ] **Step 1: Failing tests:** support entry is recorded, 404 for an unknown tree, admins 403; events filter by action prefix, tree and dates, newest first, paged, never contain passwords; vitest for the two helpers.
- [ ] **Step 2–4:** implement; the "Vào cây"/"Quản trị" buttons and `TreeSwitcher` call `POST /api/trees/{id}/support` before setting the cookie (failure to log must not block going in? **it must block**: if the call fails show an error and do not switch); home shows the last 5 events.
- [ ] **Ship:** Playwright `gd14-p4.mjs` (entering a family writes a line visible on the log page with the right label; filters; phone), docs, suites, `finish.sh`.

---

## Phase 5 — System health

### Task 10: `system_state`, worker heartbeat, health and full backup status (API)

**Files:** Create `alembic/versions/d6a8b2c50f71_system_state.py` (down `c5f7a1b49e60`), `app/models/system_state.py`, `app/core/system_health.py`, `tests/test_platform_health.py`; modify `app/jobs/reminders.py` or `scripts/run_reminders.py` (heartbeat after every round, success or failure noted), `app/core/backup_status.py` (extend), `app/routers/platform.py`, `app/core/platform_overview.py`, `alembic/env.py`.

**Interfaces:**
- Produces: table `system_state(key VARCHAR(60) PK, value TEXT NOT NULL, updated_at TIMESTAMPTZ default now)`; helper `async def set_state(db, key, value)` / `get_state`; the worker writes `reminders.last_run` (ISO UTC) after each round.
- Produces: `GET /platform/health -> PlatformHealth {database: {ok: bool, revision: str | None}, worker: {state: "ok"|"stale"|"unknown", last_run: datetime | None, age_minutes: int | None}, email: {configured: bool}, disk: {total_bytes, free_bytes, free_percent}, storage: {media_bytes: int, avatar_bytes: int}, backup: BackupStatusFull}`; `BackupStatusFull(BackupStatus)` adds `members: int | None` (from the newest backup's `MANIFEST.txt` line `members=N` when readable, else null) and `recent: list[{name, last_at, size_bytes}]` (latest 5). Worker `stale` when the last run is older than 3 hours, `unknown` with no row. Overview items: `worker_stale` (only for `stale`, href `/he-thong/he-thong`), `backup_old` (never/old, full-status wording), `disk_low` (free < 15%).
- The tree admins' `GET /admin/backup-status` is unchanged and still has no `members`.

- [ ] **Step 1: Failing tests:** heartbeat row written by the job; `worker` states for no row/fresh/4-hour-old; disk numbers come from `shutil.disk_usage` (patch it to test `disk_low`); `members` parsed from a manifest and null for a missing/garbage manifest (no crash); `recent` ordering and cap; email flag; database revision equals the `alembic_version` row; admins' endpoint still lacks `members` (regression); only superadmin.
- [ ] **Step 2–4:** implement; **Step 5: Commit.**

### Task 11: Hệ thống page (web) and ship Phase 5
- [ ] `src/app/he-thong/he-thong/page.tsx`, `SystemView.tsx`, `src/lib/platform/system.ts` (+ test: `workerSummary`, `diskSummary` with warn tones and Vietnamese sentences, reuse `formatBytes`/`backupSummary`); calm/warn cards for database, worker ("chưa có dữ liệu" when unknown), e-mail, disk, storage, backups (list of the latest 5, total members from the manifest); Playwright `gd14-p5.mjs` (states via a temp `BACKUP_DIR`, worker row set through SQL: fresh/stale/none); docs; suites; `finish.sh`.

---

## Phase 6 — Polish and runbook

### Task 12: Cross-page polish, runbook and final docs
- [ ] Extend the Playwright audit used for the admin console (`gd12-p6.mjs` pattern: 4 themes × 4 widths × all `/he-thong` pages: fits, one h1, targets ≥ 44px, contrast ≥ 4.5:1; dialogs trap focus/Esc/return focus; keyboard walkthrough) as `gd14-p6.mjs` and fix what fails.
- [ ] `DOCKER.md` runbook section "Quản trị tối cao": who can do what, creating the first superadmin (bootstrap code), pausing/deleting a family, adding/resetting a family's admin, forgotten superadmin password (`manage.py set-password`), the platform log, what the health page means. Update both `CLAUDE.md`, `docs/SAO-LUU.md`, `note/tinh-nang-app.md`, roadmap line.
- [ ] Full suites, build (dev server stopped), commit, `finish.sh`, rebuild; final whole-branch review by a fresh reviewer (most capable model) and the fix pass per the executing-plans skill.
