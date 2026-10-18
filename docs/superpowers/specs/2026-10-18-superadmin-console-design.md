# Superadmin console (trang Các họ của quản trị tối cao) — Design

Date: 2026-10-18
Status: Draft for the owner's approval. The owner asked to continue with the superadmin page right after the admin console and the
bootstrap code; the scope was left to me (as for the admin console), so everything below is **[my call]** unless marked otherwise.
It reuses the admin console's layout and conventions (`2026-10-18-admin-console-design.md`): a to-do home, large tiles, one page per area.

## Intent

The superadmin is the platform owner: usually one person (or two) running a server that hosts several families' trees. Today `/he-thong`
is a list of families with "create", "rename" and "go in". It cannot say whether anything needs attention, cannot stop or remove a
family, cannot manage a family's admins, leaves no record of what the superadmin did to the families (create, pause, delete, admin changes, going in), and says nothing
about whether the server itself is healthy. The page should let one person **look after the whole server safely**: see what needs
attention, handle the life of a family (create, pause, remove), keep each family's admin able to get in, and trust that the platform is
healthy and backed up.

## Goals

- Opening the console shows **what needs attention across all families** and how big the platform is.
- A family can be **paused** (nobody of it can sign in or use it, nothing is lost) and **resumed**; a paused family can be **deleted for good**
  behind a deliberate confirmation.
- Each family's admins can be **listed, added, re-enabled and given a new password** by the superadmin (admin of last resort).
- Everything the superadmin does **to a family from this console** — and **going in to help** — is written to a platform log the superadmin can read. (What the superadmin then does *inside* a family is already in that family's own audit log with the superadmin as the actor.)
- The superadmin can see **server health**: database and migration version, the reminder worker's last run, e-mail configured or not, disk and
  storage use, and the **full** backup status (the whole-database numbers a tree admin must not see).

## Non-goals

- Triggering or downloading backups from the web, restoring from the web (stay with `scripts/backup.sh`/`restore.sh`; see Calls).
- Moving users or members between families; merging families.
- Several superadmins managing each other, 2FA, SSO, per-family quotas or billing.
- Redesigning the families' own admin console (done) or any member-facing page.

## Anti-goals (a failure even if it technically works)

- A tree deleted by a stray tap, deleted while active, or deleted without the files going too / without a platform-log line.
- A paused family that can still sign in, or a resume that does not fully restore access.
- The superadmin locked out (the only superadmin can never be disabled/demoted from the web; granting `superadmin` stays CLI-only).
- A family left with no active admin by any action of this console (the same rule as the admin console).
- Any action by a tree admin reaching another family, or a non-superadmin reaching any platform endpoint (403, never data).
- Secrets (passwords, tokens, hashes) in a response other than the one-time password, in logs, or in platform-log rows.

## Constraints

- Same stack/conventions as the admin console: FastAPI/SQLAlchemy async/Alembic, Next.js 15/Tailwind v4 tokens, Vietnamese UI, pages without
  props, UI rules (body ≥ 16px, targets ≥ 44px, visible focus, contrast ≥ 4.5:1 on all four themes, status chips = coloured border + default
  text, confirmation for anything destructive, tables become cards on a phone). Platform endpoints depend on `require_superadmin`
  (`/trees` already does) — they must not depend on, or be changed by, the tree the superadmin currently acts on.
- Dangerous actions **ask first**: pause, resume, delete (type the family's slug), admin password reset, disabling an admin.
- Never touch the host Postgres on 5432 or the developer's own `genealogy` DB; tests use `db-test`; smoke runs use the throwaway container.

## The pages

Address space `/he-thong` (home) and `/he-thong/<area>`; the current list/create/edit UI moves unchanged into the first area.

| Area (tile) | Address | What it holds |
|---|---|---|
| Cần làm (home) | `/he-thong` | to-do list, platform numbers, tiles, last 5 platform-log lines |
| Các họ | `/he-thong/ho` | the existing list + create + rename/slug; each family gets status, last activity, admins; pause/resume/delete |
| Quản trị viên | inside a family's card (a dialog) | list admins, add, re-enable/disable, new password |
| Nhật ký nền tảng | `/he-thong/nhat-ky` | what the superadmin did: create/rename/pause/resume/delete families, admin changes, going in to help |
| Hệ thống | `/he-thong/he-thong` | database, migration version, reminder worker, e-mail, disk/storage, full backup status |

### "Cần làm" items

Computed by `GET /platform/overview`; zero-count items are left out; "Không có việc nào cần làm" when empty.

1. N họ **không có quản trị viên đang hoạt động** (e.g. the only admin was disabled) → Các họ filtered.
2. N họ có **admin chưa từng đăng nhập** sau hơn 7 ngày từ lúc tạo → Các họ.
3. N họ **đang tạm ngưng** (standing reminder, so a pause is not forgotten) → Các họ.
4. **Bộ nhắc việc (worker) không chạy** (no heartbeat for over 3 hours while it should run hourly) → Hệ thống.
5. **Chưa sao lưu / sao lưu cũ hơn 7 ngày** (the full-status version of the admins' item) → Hệ thống.
6. **Ổ đĩa còn dưới 15%** → Hệ thống.

Platform numbers on the home: number of families (active/paused), total people, total accounts, upload storage.

## Phases (build in this order; each ends shippable and merged)

### Phase 1 — Frame, overview, platform log foundation
Route group `/he-thong/*` with a shared frame (same guard, "← Các họ nền tảng", desktop section list); move the current panel into `/he-thong/ho` unchanged;
`GET /platform/overview` (to-do items 1–3 and the numbers); new table **`platform_events`** (`id`, `actor_id` SET NULL, `actor_name`, `action`, `tree_id` plain int
(no FK, survives deletion), `tree_name`, `details` JSON, `created_at`) and `app/core/platform_log.py::record`; tree create and rename (existing endpoints) start writing
`tree.create` / `tree.update`. `trees.last_activity` is **computed** (latest of the tree's audit log / users' last login), not stored.

### Phase 2 — Family life cycle
New `trees.status` (`active` | `paused`, default `active`). **Paused ⇒** login of its users is 403 `tree_paused`, `get_current_user` refuses them on every request (a paused family's existing sessions die at once,
exactly like a disabled account), guests/signup of that tree are refused, public feeds/cards/invitations of that tree answer 404, the reminder worker skips it. The superadmin can still read and act on it
(to look, or to delete). `POST /trees/{id}/pause|resume`. **`DELETE /trees/{id}`** only for a paused tree, body must repeat the slug; removes the tree's rows (members, users, media rows, audit, events, cards…) and its files under `UPLOAD_DIR` (`media/`, `media/thumbs/`, avatars) after the commit succeeds. The superadmin may delete any paused tree, including the one the acting-tree cookie points at (the cookie then simply falls back to another tree). Each action asks first and writes `tree.pause|resume|delete` (delete keeps name, slug, member/user counts in `details`).

### Phase 3 — Admins of a family
`GET /trees/{id}/admins`, `POST /trees/{id}/admins` (create a new admin account with a generated or typed password, or promote an existing member by email of that tree),
`PATCH /trees/{id}/admins/{user_id}` (`status` active/disabled), `POST /trees/{id}/admins/{user_id}/password` (generated or typed, returned once). Rules: a family always keeps one active admin
(409 otherwise), superadmins are not addressable here, another tree's user is 404. Logged as `admin.create|update|password_reset` in the platform log (never the password). Web: a dialog from the family card.

### Phase 4 — Going in to help, platform log page
`POST /trees/{id}/support` records `support.enter` (the web calls it before setting the acting-tree cookie; the existing switcher and the "Vào cây" button both use it). The platform log page
(`GET /platform/events?action=&tree_id=&since=&until=`, newest first, paged) shows who/what/when with Vietnamese labels. Home shows the last 5 lines.

### Phase 5 — System health
`GET /platform/health`: database reachable and `alembic_version`; reminder worker last run (new table **`system_state(key, value, updated_at)`**, written by `app/jobs/reminders.py` after each pass as `reminders.last_run`);
SMTP configured (host set, nothing else revealed); `shutil.disk_usage` of `UPLOAD_DIR`; upload storage (sum of `media.size` per tree plus avatar files, cached per request); and **full backup status**
(`app/core/backup_status.py` extended with `members` from `MANIFEST.txt` when readable, list of the latest 5 backups with size/age). Overview items 4–6 come from it. Read-only.

### Phase 6 — Polish
Contrast/targets/keyboard pass on the four themes at 375/768/1024/1440, copy review, docs (`CLAUDE.md` of both repos, `DOCKER.md`, `docs/SAO-LUU.md`, the feature note), the superadmin runbook ("ai vào được gì, quên mật khẩu superadmin thì làm gì") in `DOCKER.md`.

## Calls made (all **[my call]**; the owner can overrule)

1. **Delete is real but guarded**: only a paused family, slug typed, files removed, logged. (A softer alternative is pause only; deleting is what the owner needs once a family leaves.)
2. **Backups stay out of the web's hands**: the superadmin sees the full status but still creates and restores them with the scripts (a web button that dumps every family needs `pg_dump` in the API image and a download door;
   revisit separately).
3. **Pause blocks everyone of the family** including its admin, and kills sessions at once, so a pause is a real stop.
4. **Platform log is its own table**, not the families' audit log, because tree-less events (a deleted family) have nowhere to live there and tree admins must never see them.
5. **`last_activity` is computed**, no new write on every request.
6. **Superadmin accounts** are never created/changed on the web; `set-role superadmin` and the bootstrap code remain the only ways to *make* one. A forgotten superadmin password gets a new command `manage.py set-password --email …` (generates and prints one, or reads `--password`), built in Phase 3 and described in the Phase 6 runbook.
7. **"Going in" is logged by the console, not enforced by the server.** `support.enter` is written when the web calls `POST /trees/{id}/support` (the "Vào cây" button and the tree switcher both do). A superadmin who sends `X-Tree-Id` by hand is not caught; their writes inside any family still appear in that family's audit log under their name. Mirroring every in-family write into the platform log would hook every route and is not worth it.
8. **Delete has no backup precondition.** Safety = paused first + typing the slug + a dialog that shows what will go (people, accounts, files) and says it cannot be undone, with a link to the family's JSON export (`/export/data.json` while acting on it). It does not check for a recent backup (Phase 5 ships later and a backup says nothing about this family).
9. **Item "admin never logged in" is dropped from this release**: `last_login_at` is NULL for every account older than that column, so it would flood the home on day one. Items 1 and 3 already cover "no way in". Paused families are excluded from item 1 (their admins are irrelevant until resumed) and counted only by item 3.
10. **Worker heartbeat with no row yet** (fresh install or a setup without the worker) shows "chưa có dữ liệu" on the Hệ thống page and is **not** a to-do item; the item fires only when a heartbeat exists and is older than 3 hours.
11. **Adding an admin**: `users.email` is unique across the platform, so creating an admin with an email that already exists anywhere is 409 "email đã được dùng" (the caller is the superadmin, so nothing is leaked). Promoting is done by choosing one of **the family's own users** (by id): it sets role `admin` and status `active`, including for a pending or disabled user. Superadmins are never addressable.

## Left to the builder

Component/file names, response shapes beyond those named, pagination sizes, exact Vietnamese wording, icons (existing inline SVG style), the Alembic revisions
(`trees.status`, `platform_events`, `system_state`), how the tests simulate a paused tree across login/feeds/worker, and the test split per phase.

## Definition of done per phase

Spec section satisfied; backend and frontend suites green; `npm run build` and lint clean; Playwright on the throwaway stack at phone and desktop widths with no console errors; docs updated; merged to `main`
in all three repos (never pushed); the user's compose stack rebuilt.
