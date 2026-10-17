# Roles, Admin and Site Settings — Design (Giai đoạn 1)

Date: 2026-10-17
Status: Approved to build by the owner ("bắt đầu từ bước 1"); defaults below are my proposals for the open decisions D1–D7 of `../../../../docs/ke-hoach-tinh-nang.md`.

## Why

Today anyone who can reach the site can self-register and then edit or delete the whole shared
tree. Before the family is invited, the system needs roles, an approval step for new accounts,
and a way to choose between private and public read-only access.

## Decisions (my defaults — change any of them)

- **D1** One tree per deployment (no multi-tenancy).
- **D2** Default visibility is **private**; an admin can switch the site to **public read-only**.
- **D4** Default registration mode is **approval**: new accounts wait as `pending` until an admin approves.
  Modes: `open` (active at once), `approval`, `closed` (self-registration refused; the admin creates users).
  "Invite" is covered by the admin creating a user directly (no invitation links yet).

## Model

- `users.role`: `admin` | `member`. `users.status`: `pending` | `active` | `disabled`.
  Migration: every existing user becomes `admin` + `active` (the system had no other notion before).
- `site_settings(key PK, value)`: `visibility` (`private`|`public`), `registration` (`open`|`approval`|`closed`).
  Missing rows mean the defaults above.
- **Bootstrap:** while the `users` table is empty, the first registration becomes `admin` + `active`,
  whatever the registration mode (a fresh install must be usable).

## Behaviour

- `register`: `closed` → 403; otherwise creates `member` with status `active` (`open`) or `pending` (`approval`).
- `login`: wrong credentials → 401; `pending` → 403 `account_pending`; `disabled` → 403 `account_disabled`.
- `get_current_user` (every authenticated route) rejects non-`active` users with 403 even if their token is
  still valid, so disabling someone takes effect immediately.
- **Members API:** reads (`GET /members/tree`, `GET /members/{id}`) → any active user, or anybody when the
  site is `public` (guests get a **redacted** detail: `notes`, `residence`, `burial_*` are null). **All writes**
  (create/update/delete member, avatar, marriages) → **admin only** (403 for members).
- `GET /auth/me` returns `role` and `status`.
- **Admin API** (admin only): `GET /admin/users`, `POST /admin/users` (create active user with a given
  role/password), `PATCH /admin/users/{id}` (role and/or status), `GET/PUT /admin/settings`.
  The last active admin can never be demoted or disabled (409).
- **Public:** `GET /site/info` → `{visibility, registration}` (so the login/signup pages can explain
  what will happen) — no authentication.

## Frontend (genealogy-web)

- Edit controls (Sửa, Xoá, Thêm con, vợ/chồng, ảnh, "thêm người đầu tiên") only for admins.
- Header: shows the user and role, "Đăng nhập" for guests; sidebar gains "Quản trị" for admins.
- Page `/admin`: users (approve, role, disable, create) and settings (visibility, registration).
- Login/signup explain pending / disabled / closed. Middleware no longer forces `/` to `/login`
  (public mode must work); the page already redirects on a 401.

## Non-goals (later phases)

Invitation links/emails, per-field privacy (GĐ11), change requests (GĐ4), audit log, rate limiting, password policy.
