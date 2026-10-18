# Admin console (trang Quản trị của admin) — Design

Date: 2026-10-18
Status: Draft for the owner's approval (builder check done; its questions answered below as my calls). Scope for the first release was delegated to me ("bạn lên plan làm tuần tự"); the
owner decided only the **layout** (option B below). Everything else is my call and is marked **[my call]**.
The superadmin page (`/he-thong`) is a separate, later project.

## Intent

Today `/admin` is three tabs (Người dùng, Cài đặt, Quyền riêng tư) and nothing tells an admin what needs attention.
The people who administer a family tree are relatives, many of them not technical and some elderly, mostly on a phone.
The page should answer "is anything waiting for me, and is everything safe?" the moment it opens, and make every routine
job (approve a relative, hand someone a login, check the backup) a few big, obvious taps.

## Goals

- Opening Quản trị shows **what needs doing now**, each item one tap from where it is handled.
- Each area has its own page with its own address (shareable, back button works).
- The routine user jobs get easier: find a user, approve several at once, reset a forgotten password, see who has
  never logged in.
- The admin can see that data is safe: when the last backup was made (status only), and a log of security-relevant events.
- Every dangerous action asks first and leaves a line in the audit log.

## Non-goals

- The superadmin console (`/he-thong`); managing several families.
- Restoring a backup from the web page (restore stays a deliberate command-line job, `docs/SAO-LUU.md`).
- New permission levels, per-user permissions, two-factor login, SSO.
- Redesigning the rest of the app (tree, search...). Only the admin area changes.
- Replacing the member-facing pages (Yêu cầu, Nhật ký, Nhập liệu, Xuất bản keep their own pages; the console links to them).

## Anti-goals (would be a failure even if it technically works)

- An admin can lock themselves or the whole family out (last active admin demoted/disabled, password reset that leaves
  no way in).
- A destructive action happening on one stray tap, or without a trace in the audit log.
- Anything that only works on a desktop, or needs text smaller than 16px, or touch targets smaller than 44px.
- Existing admin functions (approve/disable/role change/create user, site settings, privacy levels) regress.

## Decided by the owner

- **Layout B**: Quản trị opens on a "Cần làm" (to-do) page; below it a grid of large tiles, one per area; each tile opens its
  own page with a "← Quản trị" link at the top. Tiles 2 per row on a phone, 4 per row on a desktop; on a desktop a slim
  section list on the left allows quick switching.

## Constraints

- Existing stack and conventions: Next.js 15 / React 19 / Tailwind v4 with the `heritage`/`modern` theme tokens
  (`--color-*`); FastAPI + SQLAlchemy async + Alembic. Pages under `src/app/**/page.tsx` take no props. Vietnamese UI.
- Admin routes act on one tree (the admin's, or the superadmin's chosen one); every new admin endpoint uses
  `get_write_context` and is tree-scoped; cross-tree ids are 404.
- Any new write goes through the audit log (`app/core/audit.py`) in the same transaction.
- No secrets in responses or logs (tokens, hashes). Test DB rules unchanged (throwaway Postgres only).
- UI rules from the ui-ux-pro-max pass, applied on top of the existing theme: body text ≥ 16px, line-height ~1.5,
  touch targets ≥ 44×44px with 8px+ spacing, visible 3px focus ring, contrast ≥ 4.5:1 in both themes, no emoji as icons
  (SVG only), loading and success/failure feedback for every action, confirmation for destructive actions, respect
  `prefers-reduced-motion`, tables become cards on a phone, no horizontal page scroll at 375px. The skill's generic blue
  palette was rejected: the app keeps its own heritage tokens.

## The pages

Address space `/admin` (to-do + tiles) and `/admin/<area>`. The old tab content moves unchanged into the first three areas.

| Area (tile) | Address | What it holds |
|---|---|---|
| Cần làm (home) | `/admin` | to-do list, tiles, a short "gần đây" strip (last 5 audit lines) |
| Người dùng | `/admin/nguoi-dung` | the user list and its jobs (below) |
| Cài đặt họ | `/admin/cai-dat` | existing visibility + registration; **[my call]** also the family name shown in the header is *not* editable here (it is the tree name; renaming stays with the superadmin) |
| Quyền riêng tư | `/admin/rieng-tu` | existing per-field levels |
| Nhật ký | `/admin/nhat-ky` | the existing audit log page moved/linked + security events |
| Link chia sẻ | `/admin/link` | the calendar `.ics` link (create/regenerate/remove) and the open invitation cards, each revocable |
| Sức khoẻ dữ liệu | `/admin/suc-khoe-du-lieu` | checks on the tree's data, each with a link to the person |
| Sao lưu | `/admin/sao-luu` | read-only status of the host's backups (last time, age, size, how many kept); no button, no download |
| Xuất bản | link to `/xuat-ban` | no new page: the tile links to the existing one |

### "Cần làm" (to-do) items **[my call]**

Computed by `GET /admin/overview`; each item has a count, a sentence and a target link; zero-count items are not shown, and when
none remain the box says "Không có việc nào cần làm".

1. N người đăng ký đang chờ duyệt → Người dùng (filtered to pending).
2. N yêu cầu chỉnh sửa chờ duyệt → `/yeu-cau`.
3. Chưa sao lưu N ngày (or "chưa sao lưu lần nào") when the last backup is older than 7 days → Sao lưu.
4. Cây đang **công khai** / đăng ký đang **mở** (shown as a standing notice, not a task, with a link to Cài đặt).
5. N vấn đề dữ liệu (from the health checks) → Sức khoẻ dữ liệu.
6. N tài khoản bị khoá tạm vì đăng nhập sai trong 24 giờ (from the security events) → Nhật ký.

## Phases (build in this order; each ends shippable and merged)

### Phase 1 — Frame and "Cần làm"
Routes `/admin/*` with a shared layout (section list on desktop, tiles on the home page); move the three existing tabs into
`nguoi-dung`, `cai-dat`, `rieng-tu` **without changing behaviour**; `GET /admin/overview` with the first items (1, 2, 4); sidebar item "Quản trị" keeps its
pending badge; old `/admin` tab state is gone (bookmark of `/admin` still works). No data model change.

### Phase 2 — Users, properly
- List: search by name/email, filter by status/role, shows last login time and "chưa đăng nhập lần nào"; cards on a phone.
- **Last login**: new nullable `users.last_login_at`, set at login.
- **Bulk approve** pending users; approve/disable/role change keep the existing "at least one active admin" rule and now ask first and
  write the audit log (today role/status changes are not audited).
- **Reset password** (admin sets a new one, shown once, user must... **[my call]** no forced change at first login in this release) and
  **re-activate**. A password reset never works on another tree's users or on a superadmin.
- **Link a user to a person in the tree** (`users.member_id`, nullable, unique per tree, the person must be in the same tree): the list
  shows "Họ Hàng — Nguyễn Văn Anh". Used for display only in this release (later: "my profile", targeted notifications).
- Invite by link instead of choosing a password for someone: **not in this release** (see Open decisions).

### Phase 3 — Nhật ký bảo mật and Link chia sẻ
- Audit entries for role/status/user creation/password reset/site settings changes (reuse `audit_log`, new `action` values).
- **Security events** in the same table: failed logins against an existing account (tree taken from the account), account temporarily
  locked by the rate limiter, successful login of an admin from… **[my call]** only failures and lockouts, no IP stored (privacy; behind the
  Next proxy the IP is the web container anyway). Retention: kept like the rest of the audit log.
- `/admin/nhat-ky`: filter by kind (data / people / security / settings) and date; to-do item 6.
- Link chia sẻ: manage the calendar feed link and list open invitation cards with "Đóng thiệp"/"Thu hồi".

### Phase 4 — Sức khoẻ dữ liệu
Read-only checks, computed in memory from `TreeLayout` (no schema change): possible duplicates (same name + birth year), implausible dates
(death before birth, a child born before the parent, parent–child gap < 12 years or > 70), people with no birth year
whose descendants have one, a branch head that no longer exists is impossible (FK), media files missing on disk, media rows without a
person/place/article. Each finding links to the person. No auto-fix in this release. To-do item 5.

### Phase 5 — Sao lưu: status only **[my call]**
A backup holds **every family's** data and every password hash, so a *tree* admin must never be able to download or trigger one. This
page is therefore **read-only status**: when the last backup was made, how old it is, its size, and how many are kept. It never shows the
whole-database member count (that would reveal other families' sizes) and offers no download and no "Sao lưu bây giờ" button.
- Source: the host's `./backups/` folder, which the root compose mounts **read-only** into the API (`/app/backups:ro`); the API reads the newest
  `gia-pha-*/MANIFEST.txt` (creation time, files present) and file sizes. `GET /admin/backup-status` returns
  `{state: "never" | "ok" | "old", last_at, age_days, size_bytes, kept}`.
- A missing or empty folder means `never` ("Chưa có bản sao lưu nào được ghi nhận trên máy chủ", with a pointer to `docs/SAO-LUU.md`); it is
  not an error.
- To-do item 3 appears when the state is `never` or the last backup is older than 7 days.
- Triggering and downloading backups, and restoring, belong to the future superadmin console (platform level), not here.

### Phase 6 — Polish
Visual pass on all admin pages at 375/768/1024/1440 px in both themes, keyboard-only walkthrough, screen-reader labels, empty/loading/error
states, copy review; update docs (`CLAUDE.md` of both repos, `DOCKER.md`, the feature note).

## Calls made on open questions (all **[my call]**, listed so the owner can overrule them)

1. **Backups are platform-level** (see Phase 5): tree admins get status only; actions and downloads wait for the superadmin console.
2. **Linking users to people (Phase 2)** is included, display-only (adds `users.member_id` and a picker). If unwanted the phase shrinks.
3. **Invite by link** is out of this release; interim: the admin sets a temporary password, shown once.
4. **"Last login" wording**: `users.last_login_at` is new, so existing users have no value; the list says **"Chưa ghi nhận"** (not "chưa đăng nhập
   lần nào") for them. It only becomes accurate as people log in.
5. **Security events** (Phase 3): a failed login against an existing account is recorded, but at most up to the lockout threshold; when the
   limiter locks the account **one** "bị khoá tạm" event is written and nothing more while it is locked (no log flooding). The limiter itself stays
   in memory, so a restart forgets who is locked but the written events remain; to-do item 6 counts the written lockout events of the last 24 hours.
6. **All the other [my call] items** in this document stand until the owner overrules them; this document needs the owner's approval before
   anything is built.

## What is left to the builder

Exact component structure and file names, the shape of `GET /admin/overview`, pagination size of the user list, wording of every Vietnamese
label (follow existing tone), icon choice (existing Lucide-style inline SVGs), the migration for `last_login_at`/`member_id`, and the test
split (backend per phase with the throwaway Postgres; frontend pure-logic tests; Playwright run on the throwaway stack after each phase).

## Definition of done per phase

Spec section satisfied; backend tests and frontend tests green; `npm run build` and lint clean; Playwright check on the throwaway stack at a
phone viewport and a desktop one with no console errors; docs updated; committed in all three repos and merged to `main`; user's compose stack rebuilt.
