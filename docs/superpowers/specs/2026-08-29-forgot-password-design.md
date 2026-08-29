# Forgot Password — Design

## Goal

Let a user who forgot their password request a reset link by email and
set a new password from it, without leaking whether a given email is
registered.

## Data model

New table `password_reset_tokens`:

| column        | type      | notes                                             |
|---------------|-----------|-----------------------------------------------------|
| `id`          | int PK    |                                                      |
| `user_id`     | int FK → `users.id`, `ON DELETE CASCADE`            |
| `token_hash`  | `String(64)`, unique, indexed | SHA-256 hex digest of the raw token — the raw token itself is never persisted, only emailed |
| `expires_at`  | timestamptz, not null | 30 minutes after creation                          |
| `used_at`     | timestamptz, nullable | set once the token is redeemed; a token with `used_at` set is permanently spent |
| `created_at`  | timestamptz, server default `now()` |                                |

A token is single-use: `reset-password` checks `used_at IS NULL` and
`expires_at > now()` before honoring it, and sets `used_at` in the same
request that changes the password. This is a deliberate choice over
reusing the existing JWT infrastructure — a leaked JWT-based reset
token would stay valid for its whole window even after being redeemed
once; a DB-backed single-use token closes that window immediately.

## Email delivery

`app/core/email.py` gets one function:

```python
def send_password_reset_email(to_email: str, reset_url: str) -> None:
    ...
```

It sends a plain-text email via Python's standard-library `smtplib` +
`email.mime.text.MIMEText` — no new dependency. Configuration comes
from new `Settings` fields (`app/core/config.py`), all read from
`.env`: `smtp_host`, `smtp_port` (default `587`), `smtp_username`,
`smtp_password`, `smtp_from` (falls back to `smtp_username` if blank),
`smtp_use_tls` (default `True`).

`smtplib` is synchronous; the router calls it via `await
asyncio.to_thread(send_password_reset_email, ...)` so a slow SMTP
round-trip doesn't block the event loop for other requests. Tests never
hit a real SMTP server — they monkeypatch
`app.routers.auth.send_password_reset_email` (the name as imported
into that module) with a stub that records its arguments, matching how
tests already avoid touching real Postgres/disk for other features.

## API

**`POST /auth/forgot-password`** — body `{ "email": "..." }`.
- Always responds `200` with a fixed generic body regardless of
  whether the email is registered — this is the anti-enumeration
  measure, not an implementation detail to skip.
- If a user with that email exists: generate `secrets.token_urlsafe(32)`,
  store its SHA-256 hash with a 30-minute expiry, and send an email
  whose body contains `{FRONTEND_ORIGIN}/reset-password?token=<raw
  token>`.
- If no user exists: do nothing further (no token created, no email
  sent) — but still return the same `200` body as the success case.

**`POST /auth/reset-password`** — body `{ "token": "...", "new_password": "..." }`
(`new_password` reuses the existing `min_length=8` rule from
`UserCreate.password`).
- Hash the incoming token and look it up by `token_hash`.
- `400` if not found, already used (`used_at` set), or expired.
- Otherwise: hash `new_password` with the existing `hash_password`,
  update the user's `hashed_password`, mark the token's `used_at`,
  commit. `204 No Content` on success.

Both routes live in the existing `app/routers/auth.py` (no new
router) and are intentionally **not** behind `get_current_user` — a
user requesting a reset is, by definition, not logged in.

## Frontend

- `src/components/FormExtra.tsx`'s existing "Forgot your password?"
  link (currently `href="#"`, a pre-existing placeholder) now points
  at `/forgot-password`, as a Next `<Link>` for consistency with
  `AuthHeader`.
- New page `/forgot-password`: an email field, submits to
  `/api/auth/forgot-password`, and — on any successful response —
  replaces the form with a fixed message ("if that email exists, a
  reset link has been sent"), never revealing whether the email was
  found. A failed *request* (network error, non-2xx) shows a distinct
  "couldn't reach the server" message — that's about the request
  failing, not about the email's existence, so it doesn't reintroduce
  the leak.
- New page `/reset-password?token=...`: reads `token` from the query
  string (`useSearchParams`, so the form component needs a `<Suspense>`
  boundary around it per Next 15's requirement for that hook), a new
  password field + confirmation field, submits to
  `/api/auth/reset-password`. Success redirects to `/login`. Failure
  shows an inline error (mismatched confirmation, or an expired/invalid
  token message from a non-2xx response).
- Neither page is added to `middleware.ts`'s `PROTECTED_PATHS` — they
  must be reachable without being logged in, which is already true by
  default (the matcher only lists `/` and `/genealogy-tree`).

## Testing

Backend (pytest):
- Model: a `PasswordResetToken` row can be created; `used_at` defaults
  to `None`.
- `POST /auth/forgot-password`:
  - For an existing user: the (monkeypatched) email-send stub is
    called once with that user's email and a `reset_url` containing
    `/reset-password?token=`; response is `200`.
  - For a nonexistent email: the stub is **not** called; response is
    still `200` with the same body shape (verifies no enumeration
    leak).
- `POST /auth/reset-password`:
  - A valid, unexpired, unused token successfully changes the
    password — verified by logging in with the new password
    afterward (and confirming the old password no longer works).
  - An unknown token → `400`.
  - A token whose `expires_at` is in the past → `400` (test by
    monkeypatching the router's expiry-minutes constant to a negative
    number so a freshly created token is already expired).
  - Reusing an already-redeemed token → `400`.
  - `new_password` shorter than 8 chars → `422`.

Frontend: no new Vitest coverage (these are thin API-calling forms,
same category as the existing login/signup forms which also have no
unit tests) — verified via `tsc --noEmit` + `eslint` + a real-browser
Playwright pass. Since there is no real SMTP account configured for
this dev environment, verification points the running backend at a
throwaway local debug SMTP sink (`uv run --with aiosmtpd python -m
aiosmtpd -n -l localhost:1025` — an ephemeral dependency via `uv run
--with`, not added to `pyproject.toml`) via `SMTP_HOST=localhost`,
`SMTP_PORT=1025`, `SMTP_USE_TLS=false` in the backend's environment for
that run only; the sink prints each received email's raw body
(including the `reset_url` and its token) to its own stdout, which the
verification script reads to extract the token before driving
`/reset-password` in the browser. Confirms: requesting a reset for a
real test account, setting a new password, logging in with the new
password, and confirming the old password no longer works.
