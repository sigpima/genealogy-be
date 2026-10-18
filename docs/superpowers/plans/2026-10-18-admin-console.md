# Admin console Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn `/admin` into a to-do home with large tiles and separate pages (users, settings, privacy, audit/security, share links, data health, backup status), as designed for the family admin on a phone.

**Architecture:** Backend adds a handful of tree-scoped admin endpoints (`/admin/overview`, user jobs, `/admin/data-health`, `/admin/backup-status`, `/admin/shares`) plus audit/security-event writes, all through `get_write_context`. Frontend replaces the tab page with a route group `/admin/*` sharing one frame (`AdminFrame`), where each area is a page reusing or replacing today's panels. Phases ship one by one (each merged to `main`).

**Tech Stack:** FastAPI/SQLAlchemy async/Alembic/pytest (real Postgres via `db-test`), Next.js 15/React 19/Tailwind v4 tokens, vitest, Playwright (throwaway stack).

**Spec:** `docs/superpowers/specs/2026-10-18-admin-console-design.md` (read it first; its "Calls made" section is binding).

## Global Constraints

- Every new admin endpoint depends on `get_write_context` and filters by `ctx.tree.id`; ids of another tree answer **404**, members **403**, guests **401**.
- Every new write calls `app/core/audit.py::record` in the caller's transaction; no secrets (tokens, hashes, temporary passwords) in audit rows, responses beyond the one-time password, or logs.
- UI: body text ≥ 16px, touch targets ≥ 44×44px with ≥ 8px between, visible 3px focus ring, contrast ≥ 4.5:1 in `heritage` and `modern`, SVG icons only (no emoji), loading + success + failure feedback on every action, confirmation before destructive actions, `prefers-reduced-motion` respected, tables become cards on a phone, no horizontal page scroll at 375px. Keep the app's own `--color-*` tokens (no new palette).
- Vietnamese UI text; pages under `src/app/**/page.tsx` take no props; vitest imports in `src/lib` are relative (no `@/` alias).
- Backups: tree admins get **status only** — no download, no trigger, no whole-database member count.
- "Last login" for users without a value reads **"Chưa ghi nhận"**.
- Never touch the host Postgres on 5432 or the developer's own `genealogy` DB; tests run on `db-test` (name ends `_test`); smoke runs use the throwaway container.
- Nothing is pushed to any remote; commits carry `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.

## Review Focus

- A tree admin calling any new endpoint with another tree's user/card/person ids → 404, never data (tests in Tasks 1, 4, 8, 10).
- Bulk approve / role change / disable can never leave a tree with no active admin, and bulk approve ignores users who are not `pending` (Task 4).
- Password reset refuses superadmins, other trees' users and the caller's own account is allowed but returns the new password once and never logs it (Task 4).
- `backups/` missing, empty, containing garbage folders or an unreadable/odd `MANIFEST.txt` → status `never`/ignored entry, never a 500 (Task 11).
- Failed-login events cannot flood the log: at most 8 per account per window plus one lock event; unknown emails write nothing (Task 7).
- A person linked to a user is deleted → the link clears (FK `SET NULL`), the user list still loads (Task 4).

---

## Phase 1 — Frame and "Cần làm"

### Task 1: `GET /admin/overview`

**Files:**
- Create: `app/core/admin_overview.py`, `app/schemas/admin_overview.py`, `tests/test_admin_overview.py`
- Modify: `app/routers/admin.py`

**Interfaces:**
- Produces: `class TodoItem(BaseModel): key: str; count: int; text: str; href: str; kind: Literal["task","notice"]` and `class Overview(BaseModel): items: list[TodoItem]; counts: dict[str, int]` where `counts` has `members`, `users`, `pending_users`, `pending_requests`.
- Produces: `async def compute_overview(db: AsyncSession, tree: Tree, settings: dict[str, str]) -> Overview` in `app/core/admin_overview.py`; endpoint `GET /admin/overview -> Overview`.

- [ ] **Step 1: Write failing tests** in `tests/test_admin_overview.py` (fixtures like `tests/test_privacy.py`: two trees, `admin_a`, `member_a`, `admin_b`): `test_pending_users_and_requests_are_counted` (2 pending users, 1 pending request → items keys `pending_users` count 2 href `/admin/nguoi-dung?trang-thai=pending`, `pending_requests` count 1 href `/yeu-cau`), `test_zero_items_are_left_out` (fresh tree → no `task` items), `test_public_tree_and_open_registration_are_notices` (settings visibility=public, registration=open → items `public_tree` and `open_registration` with kind `notice`, href `/admin/cai-dat`), `test_counts_are_this_trees_only` (other tree's users/members not counted), `test_members_403_guests_401`.
- [ ] **Step 2: Run** `.venv/bin/pytest tests/test_admin_overview.py -q` → FAIL (404 route).
- [ ] **Step 3: Implement** `compute_overview` with three COUNT queries (users where `status='pending'`, `ChangeRequest` pending, members) and the two notices; text in Vietnamese ("N người đăng ký đang chờ duyệt", "N yêu cầu chỉnh sửa chờ duyệt", "Cây đang công khai: ai cũng xem được", "Đăng ký đang mở: ai cũng tự đăng ký được"); register the route in `app/routers/admin.py`. Later tasks append items by extending `compute_overview` (same function, new keys).
- [ ] **Step 4: Run tests** → PASS. **Step 5: Commit** `feat(admin): overview endpoint`.

### Task 2: Admin frame, home and the three moved pages (web)

**Files:**
- Create: `src/lib/admin/sections.ts`, `src/lib/admin/sections.test.ts`, `src/components/admin/AdminFrame.tsx`, `src/components/admin/AdminHome.tsx`, `src/app/admin/nguoi-dung/page.tsx`, `src/app/admin/cai-dat/page.tsx`, `src/app/admin/rieng-tu/page.tsx`
- Modify: `src/app/admin/page.tsx` (becomes the home), `src/components/layout/Sidebar.tsx` (unchanged link; confirm badge still works)

**Interfaces:**
- Produces: `type AdminSection = { id: string; href: string; label: string; hint: string; icon: ComponentType; ready: boolean }`; `export const SECTIONS: AdminSection[]` in `sections.ts` with ids `users` (`/admin/nguoi-dung`), `settings` (`/admin/cai-dat`), `privacy` (`/admin/rieng-tu`), `audit` (`/admin/nhat-ky`), `shares` (`/admin/link`), `health` (`/admin/suc-khoe-du-lieu`), `backup` (`/admin/sao-luu`), `publish` (`/xuat-ban`); `ready` is false for sections whose phase has not shipped (they are not rendered); `export function visibleSections(): AdminSection[]`; `export type TodoItem` mirroring the API (`key,count,text,href,kind`).
- Produces: `<AdminFrame title: string; children>` (page wrapper: `AppShell` with `active="admin"`, session/redirect guard copied from the current `admin/page.tsx`, "← Quản trị" link, desktop-only slim section list); `<AdminHome user>`.

- [ ] **Step 1: Write failing tests** `sections.test.ts`: `visibleSections()` returns only `ready` ones in the order users, settings, privacy, publish (initially); every `href` is unique; `/xuat-ban` is the only href outside `/admin/`.
- [ ] **Step 2: Run** `npx vitest run src/lib/admin` → FAIL.
- [ ] **Step 3: Implement** `sections.ts`; `AdminFrame` holds the redirect logic (not signed in → `/login`, not admin → `/`) and the loading spinner; the three pages render `<AdminFrame title="…">` around `UsersPanel` (with `onPendingCount` ignored for now), `SettingsPanel`, `PrivacyPanel` unchanged; `AdminHome` fetches `/api/admin/overview` and renders the "Cần làm" box (each item a ≥44px link, notices styled quieter, empty state "Không có việc nào cần làm") above a tile grid (`grid-cols-2 lg:grid-cols-4`, each tile ≥ 96px tall, label ≥ 16px, a count badge when the matching to-do item exists); `src/app/admin/page.tsx` renders `<AdminFrame><AdminHome/></AdminFrame>`. `middleware.ts` matcher already covers `/admin/:path*`.
- [ ] **Step 4:** `npx vitest run && npx tsc --noEmit && npm run lint` → clean (lint: only the pre-existing `<img>` warning).
- [ ] **Step 5: Commit** `feat(admin): console frame, home and moved pages`.

### Task 3 (ship Phase 1): verify, document, merge

- [ ] Throwaway stack (`up.sh` pattern, dev DB `genealogy_smoke`), Playwright script `gd12-p1.mjs` at 390×800 and 1440×900: home shows the to-do box with a pending user created through the API and the tile grid (2 columns on phone, 4 on desktop); each tile opens its page and "← Quản trị" returns; old behaviours still work (approve a pending user, change a setting, change a privacy level); no console errors; screenshots viewed.
- [ ] Docs: `genealogy-web/CLAUDE.md` (admin route layout, `sections.ts` is where a new area is registered), `genealogy-api/CLAUDE.md` (`/admin/overview`), `docs/ke-hoach-tinh-nang.md` line.
- [ ] Full suites (`pytest`, `vitest`, `npm run build`), commit all three repos, fast-forward `main`, `docker compose up --build -d`.

---

## Phase 2 — Users, properly

### Task 4: Migration, last login and the user jobs (API)

**Files:**
- Create: `alembic/versions/a3d5e9f27c48_admin_users.py` (down_revision `f2c4d8e19b36`), `tests/test_admin_users.py`
- Modify: `app/models/user.py`, `alembic/env.py` (only if imports need it), `app/schemas/admin.py`, `app/routers/admin.py`, `app/routers/auth.py` (set `last_login_at` on a successful login)

**Interfaces:**
- Produces columns: `users.last_login_at TIMESTAMPTZ NULL`; `users.member_id INTEGER NULL REFERENCES members(id) ON DELETE SET NULL`, unique where not null.
- Produces schemas: `AdminUserRead(UserRead)` adds `last_login_at: datetime | None`, `member: PersonRef | None` (`PersonRef` from `app/schemas/search.py`); `AdminUserUpdate` gains `member_id: int | None` (use `model_fields_set` so an omitted field is "unchanged" and explicit `null` unlinks); `class BulkApprove(BaseModel): ids: list[int]` (1–200); `class PasswordReset(BaseModel): password: str | None = Field(default=None, min_length=8)`; `class PasswordResetResult(BaseModel): password: str`.
- Produces endpoints (all admin, tree-scoped, audited): `GET /admin/users?q=&status=&role=` (q folds diacritics over name and email, via `app/core/text.py::fold`, returns `list[AdminUserRead]` ordered by `id`); `POST /admin/users/approve` → `{approved: list[int]}` (only `pending` users of this tree, others skipped silently); `POST /admin/users/{id}/password` → `PasswordResetResult` (generated with `secrets.token_urlsafe(9)` when none given); `PATCH /admin/users/{id}` also accepts `member_id`.
- Audit actions written: `user.create`, `user.update` (changes `{role|status|member_id: [old,new]}`), `user.approve` (one row per approved user), `user.password_reset` (no password in `details`).

- [ ] **Step 1: Write failing tests** (`test_admin_users.py`): `test_login_sets_last_login_at`; `test_list_filters_by_status_role_and_folded_query` (query `nguyen` finds "Nguyễn"); `test_bulk_approve_only_pending_of_this_tree` (ids include an active user, another tree's pending user → only this tree's pending approved, response lists them); `test_role_and_status_changes_are_audited` and `test_last_active_admin_cannot_be_demoted_or_disabled` (existing rule, 409, still holds through PATCH); `test_password_reset_returns_password_once_and_user_can_log_in_with_it`, `…_given_password_is_used`, `…_refuses_superadmin_other_tree_and_unknown` (404), `…_not_in_audit_details`; `test_link_user_to_member` (same tree OK; other tree's member 404; member already linked to another user 409; unlink with explicit null); `test_deleting_a_linked_member_clears_the_link_and_list_still_loads`; `test_members_403`.
- [ ] **Step 2: Run** `.venv/bin/pytest tests/test_admin_users.py -q` → FAIL.
- [ ] **Step 3: Implement** migration + model columns, schemas and routes as in Interfaces; `create_user` and `update_user` gain audit rows; reuse the existing last-admin guard unchanged. Keep `UserRead` for `/auth/me` unchanged.
- [ ] **Step 4: Run** the new file plus `tests/test_roles_admin.py tests/test_roles_auth.py tests/test_auth.py` → PASS.
- [ ] **Step 5: Commit** `feat(admin): last login, user search, bulk approve, password reset, person link`.

### Task 5: Users page (web)

**Files:**
- Create: `src/components/admin/UsersView.tsx`, `src/components/common/ConfirmDialog.tsx`, `src/lib/admin/users.ts`, `src/lib/admin/users.test.ts`
- Modify: `src/app/admin/nguoi-dung/page.tsx` (render `UsersView`), `src/lib/admin/sections.ts` (nothing new); delete `src/components/admin/UsersPanel.tsx` once unused

**Interfaces:**
- Produces in `users.ts`: `type AdminUser` (adds `last_login_at: string | null`, `member: {id,name} | null`); `lastLoginLabel(iso: string | null, now: Date): string` ("Chưa ghi nhận", "Hôm nay", "Hôm qua", "N ngày trước", else `dd/mm/yyyy`); `buildUsersQuery(f: {q: string; status: string; role: string}): string`; `canApproveAll(users: AdminUser[]): number[]` (ids of pending ones).
- Produces `<ConfirmDialog title message confirmLabel danger? onConfirm onCancel>` (`role=dialog aria-modal`, Esc cancels, focus starts on the safe button).
- Consumes: Task 4 endpoints.

- [ ] **Step 1: Failing tests** `users.test.ts` for the three helpers (labels at the boundaries; query omits blank filters; only pending ids).
- [ ] **Step 2:** `npx vitest run src/lib/admin/users.test.ts` → FAIL.
- [ ] **Step 3: Implement** helpers, `ConfirmDialog`, and `UsersView`: search box + status/role selects (≥44px); on phones each user is a card (name, email, role/status chips, last login, linked person), on ≥ md a table; actions per user: duyệt, vô hiệu hoá/kích hoạt lại, đổi vai trò, "Đặt lại mật khẩu" (dialog shows the new password once with a copy button and the warning "Chỉ hiện một lần"), "Liên kết với người trong cây" (`PersonPicker`, unlink option); every role/status change and bulk "Duyệt tất cả (N)" goes through `ConfirmDialog`; success/failure messages in a `role=status`/`alert` line; the existing create-user form stays (collapsed by default on phones). `?trang-thai=pending` pre-selects the status filter.
- [ ] **Step 4:** `npx vitest run && npx tsc --noEmit && npm run lint` → clean. **Step 5: Commit** `feat(admin): users page`.

### Task 6 (ship Phase 2): verify, document, merge

- [ ] Playwright `gd12-p2.mjs` (phone + desktop): search without accents finds a user; bulk approve with confirm; reset password → new password shown once and works for login; link/unlink a person; demoting the only admin shows the 409 message; the "Chưa ghi nhận" label for an old user; no console errors; screenshots viewed.
- [ ] Docs (both `CLAUDE.md`, roadmap), full suites, commit, merge, rebuild stack (the migration runs at API start; check `docker compose logs api` shows `a3d5e9f27c48`).

---

## Phase 3 — Nhật ký bảo mật and link chia sẻ

### Task 7: Settings audit and security events (API)

**Files:**
- Create: `app/core/security_events.py`, `tests/test_security_events.py`
- Modify: `app/routers/admin.py` (`update_settings` audited as `settings.update` with `{key: [old,new]}`), `app/core/rate_limit.py` (add `RateLimiter.count(key: str, window: float) -> int`), `app/routers/auth.py` (login failure hook)

**Interfaces:**
- Produces: `def record_failed_login(db: AsyncSession, user: User, failures_now: int, limit: int) -> None` in `security_events.py`: adds `audit_log` row `security.login_failed` (tree = `user.tree_id`, actor_name = user's email, `details={"failures": n}`) while `failures_now <= limit`, plus exactly one `security.locked` row when `failures_now == limit`, nothing after; users with `tree_id is None` (superadmin) write nothing. Unknown emails write nothing.

- [ ] **Step 1: Failing tests:** `test_failed_logins_are_recorded_up_to_the_limit_then_one_lock_event` (10 wrong passwords with the limiter on → 8 `login_failed` + 1 `locked`, the rest 429 with no rows), `test_unknown_email_writes_nothing`, `test_wrong_password_for_superadmin_writes_nothing`, `test_pending_or_disabled_login_is_not_a_failure_event`, `test_settings_change_is_audited_with_old_and_new`, `test_unchanged_settings_write_no_audit_row`.
- [ ] **Step 2:** run → FAIL. **Step 3: Implement** (login handler commits the event row when it records a failure; keep the 401 response unchanged). **Step 4:** run plus `tests/test_rate_limit.py tests/test_auth.py` → PASS. **Step 5: Commit** `feat(admin): audit settings, record failed logins and lockouts`.

### Task 8: Audit filters, overview item 6, share links (API)

**Files:**
- Create: `app/core/audit_kinds.py`, `tests/test_admin_shares.py`
- Modify: `app/routers/audit.py`, `app/core/admin_overview.py`, `app/routers/invitations.py` (admin `GET /cards`), `app/routers/admin.py` (`GET /admin/shares`), `tests/test_audit.py` (add cases)

**Interfaces:**
- Produces: `KINDS: dict[str, tuple[str, ...]]` in `audit_kinds.py` mapping `data` → prefixes `member.`,`marriage.`,`branch.`,`media.`,`place.`,`article.`,`timeline.`,`poem.`,`event.`,`card.`,`request.`; `people` → `user.`; `security` → `security.`; `settings` → `settings.`,`privacy.`; `def action_filter(kind: str)` returning a SQLAlchemy clause; `GET /audit?kind=&since=&until=` (ISO dates, inclusive; unknown kind → 422).
- Produces: `GET /cards?open=true` (admin, tree-scoped) → `list[CardRead]` of cards that are not closed and not past `closes_on`; `GET /admin/shares -> Shares {calendar: {enabled: bool, path: str | None}, open_cards: int}`; overview item `locked_accounts` (count of `security.locked` rows in the last 24 h, kind `task`, href `/admin/nhat-ky?loai=security`).
- Actions on shares reuse existing endpoints: `POST/DELETE /calendar/subscription`, `PATCH /cards/{id}` (`closed`).

- [ ] **Step 1: Failing tests:** `test_audit_filters_by_kind_and_dates` (rows of each action family; `kind=security` returns only `security.*`; `since` after a row excludes it), `test_unknown_kind_422`, `test_overview_counts_recent_locks_only` (a 2-day-old lock row not counted), `test_open_cards_lists_only_open_cards_of_this_tree`, `test_shares_reports_calendar_state_and_open_card_count`, other-tree and member-403 cases.
- [ ] **Step 2:** run → FAIL. **Step 3: Implement.** **Step 4:** run these plus `tests/test_audit.py tests/test_invitations.py tests/test_admin_overview.py` → PASS. **Step 5: Commit** `feat(admin): audit kinds, share links summary, lock to-do item`.

### Task 9: Nhật ký and Link pages (web) and ship Phase 3

**Files:**
- Create: `src/app/admin/nhat-ky/page.tsx`, `src/app/admin/link/page.tsx`, `src/components/admin/SharesView.tsx`, `src/lib/admin/audit.ts`, `src/lib/admin/audit.test.ts`
- Modify: `src/components/audit/AuditView.tsx` (kind chips + date range, reads `?loai=` and `?tu=`/`?den=`), `src/lib/admin/sections.ts` (`audit`, `shares` become `ready`), `src/app/nhat-ky/page.tsx` (keep working; link to the new one)

**Interfaces:**
- Produces in `audit.ts`: `KIND_LABELS: Record<'data'|'people'|'security'|'settings', string>` ("Dữ liệu", "Người dùng", "Bảo mật", "Cài đặt"); `actionLabel(action: string): string` (Vietnamese sentence for each known action, fallback to the raw action); `buildAuditQuery(f: {kind?: string; since?: string; until?: string; memberId?: number}, offset: number): string`.

- [ ] **Step 1: Failing tests** for `actionLabel` (all of `user.*`, `security.*`, `settings.update`, `privacy.update` mapped, unknown returns input), `buildAuditQuery`.
- [ ] **Step 2–4:** implement pages (Nhật ký: chips for the four kinds + "Tất cả", date inputs, security rows visually distinct but not by colour alone; Link: calendar link card with copy/regenerate/remove behind `ConfirmDialog`, list of open cards with "Đóng thiệp"), run vitest/tsc/lint.
- [ ] **Step 5 (ship):** Playwright `gd12-p3.mjs` (10 wrong logins → lock row visible under Bảo mật and counted on the home to-do; settings change visible; calendar link regenerate; close a card), docs, full suites, commit, merge, rebuild.

---

## Phase 4 — Sức khoẻ dữ liệu

### Task 10: Data health checks (API) and page (web)

**Files:**
- Create: `app/core/data_health.py`, `tests/test_data_health.py`, `src/app/admin/suc-khoe-du-lieu/page.tsx`, `src/components/admin/HealthView.tsx`, `src/lib/admin/health.ts`, `src/lib/admin/health.test.ts`
- Modify: `app/routers/admin.py` (`GET /admin/data-health`), `app/core/admin_overview.py` (item `data_issues`, href `/admin/suc-khoe-du-lieu`), `src/lib/admin/sections.ts`

**Interfaces:**
- Produces: `@dataclass class Finding: kind: str; severity: Literal["warning","info"]; member_id: int | None; member_name: str | None; message: str`; `def check_layout(layout: TreeLayout) -> list[Finding]` (pure) with kinds `duplicate_name_year` (same folded name and birth year), `death_before_birth`, `child_before_parent` (child birth year < parent birth year), `parent_age_gap` (< 12 or > 70 years), `ancestor_gap_undated` (info: no birth year but a descendant has one); `async def check_media(db, tree_id, upload_dir: Path) -> list[Finding]` (kinds `media_file_missing`, `media_orphan` with no member/place/article); `GET /admin/data-health -> {findings: list[FindingRead], counts: dict[str,int]}`.
- Web: `groupFindings(findings): {kind: string; label: string; items: Finding[]}[]`, each item links to `/?focus=<member_id>`.

- [ ] **Step 1: Failing tests** in `test_data_health.py`: one test per kind with a minimal tree (e.g. `test_child_born_before_parent_is_flagged`, `test_parent_gap_under_12_and_over_70`, `test_duplicates_ignore_accents_and_case`, `test_spouses_are_not_checked_as_children`, `test_missing_media_file_is_flagged` using a tmp upload dir), `test_clean_tree_has_no_findings`, `test_other_trees_are_not_checked`, `test_members_403`, `test_overview_counts_issues`; vitest for `groupFindings`.
- [ ] **Step 2–4:** implement, run `pytest tests/test_data_health.py tests/test_admin_overview.py`, vitest/tsc/lint.
- [ ] **Step 5 (ship):** Playwright `gd12-p4.mjs` (seed a tree with a child older than the father and a duplicate; findings listed, link opens the person; clean tree shows "Dữ liệu ổn"), docs, suites, commit, merge, rebuild.

---

## Phase 5 — Sao lưu (status only)

### Task 11: Backup status (API)

**Files:**
- Create: `app/core/backup_status.py`, `tests/test_backup_status.py`
- Modify: `app/core/config.py` (`backup_dir: str = "/app/backups"`), `app/routers/admin.py`, `app/core/admin_overview.py`, `docker-compose.yml` (mount `./backups:/app/backups:ro` on `api`), `.env.example`

**Interfaces:**
- Produces: `class BackupStatus(BaseModel): state: Literal["never","ok","old"]; last_at: datetime | None; age_days: int | None; size_bytes: int | None; kept: int`; `def read_backup_status(directory: Path, now: datetime, old_after_days: int = 7) -> BackupStatus` (pure over the filesystem: considers only subfolders named `gia-pha-YYYYmmdd-HHMMSS` that contain `database.dump`; time comes from the folder name, size = dump + uploads archive sizes; unreadable/odd entries are skipped); `GET /admin/backup-status -> BackupStatus`; overview item `backup_old` (kind `task`, href `/admin/sao-luu`) when state is `never` or `old`.

- [ ] **Step 1: Failing tests** with `tmp_path`: missing dir → `never`; empty dir → `never`; folder without `database.dump` ignored; two valid folders → `kept=2`, newest chosen, `age_days` right for a fixed `now`, `state="old"` after 7 days; a folder with a malformed name ignored; unreadable manifest irrelevant (not read); endpoint test patches `get_settings().backup_dir`; response has no `members` field; members 403; overview shows `backup_old` when never.
- [ ] **Step 2–4:** implement and run. **Step 5: Commit** `feat(admin): read-only backup status`.

### Task 12: Sao lưu page (web) and ship Phase 5

**Files:**
- Create: `src/app/admin/sao-luu/page.tsx`, `src/components/admin/BackupView.tsx`, `src/lib/admin/backup.ts`, `src/lib/admin/backup.test.ts`
- Modify: `src/lib/admin/sections.ts` (`backup` ready)

**Interfaces:**
- Produces: `backupSummary(s: BackupStatus, now?: Date): {tone: "ok"|"warn"; headline: string; detail: string}` ("Bản sao lưu gần nhất: 3 ngày trước (dd/mm/yyyy hh:mm)"; for `never`: "Chưa có bản sao lưu nào được ghi nhận trên máy chủ" with detail pointing at `docs/SAO-LUU.md` and the cron line); `formatBytes(n: number): string`.

- [ ] Tests, implement (no buttons that trigger or download; the "how to back up" text is copyable), vitest/tsc/lint.
- [ ] **Ship:** with the throwaway stack create `backups/gia-pha-<stamp>/database.dump` fixtures in a temp dir mounted via `BACKUP_DIR` env; Playwright `gd12-p5.mjs` shows `ok`, `old` and `never` states; on the user's real stack `docker compose up --build -d` then check the page honestly reports whatever `./backups` holds (the folder may not exist: `never`); docs (`DOCKER.md`, `docs/SAO-LUU.md` mention the page), suites, commit, merge.

---

## Phase 6 — Polish

### Task 13: Cross-page polish and accessibility pass

**Files:** touches only `src/components/admin/*`, `src/app/admin/**`, `src/lib/admin/*`.

- [ ] Playwright `gd12-p6.mjs` at 375, 768, 1024, 1440 px in both themes (`data-theme` heritage/modern): assert no horizontal scroll (`document.documentElement.scrollWidth <= innerWidth`), every button/link on the admin pages has a bounding box ≥ 44×44, every dialog traps focus and closes on Esc, every page has one `h1`, keyboard-only walkthrough of home → users → approve with confirm; fix what fails.
- [ ] Contrast spot-check of chips and notices in both themes with a small script computing ratios from computed styles (≥ 4.5:1) — fix tokens usage, not the palette.
- [ ] Copy review of all new Vietnamese strings; empty/loading/error states present on every page.
- [ ] Update `genealogy-web/CLAUDE.md`, `genealogy-api/CLAUDE.md`, `DOCKER.md`, `note/tinh-nang-app.md` (admin section), `docs/ke-hoach-tinh-nang.md`; full suites; commit; merge; rebuild; write the final report listing leftovers (superadmin console, backup trigger/download, invite-by-link, data auto-fix).
