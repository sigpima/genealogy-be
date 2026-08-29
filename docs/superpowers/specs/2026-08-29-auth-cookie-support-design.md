# Auth Cookie + CORS Support — Design Spec

Date: 2026-08-29
Status: Approved for implementation planning

## Context

`genealogy-web` (a separate origin, `http://localhost:3000`) is being wired
up to call this API's existing `/auth/register`, `/auth/login`,
`/auth/me` for real. The frontend design (see `genealogy-web`'s
`docs/superpowers/specs/`) requires the JWT to live in an **httpOnly
cookie** set by this API, plus CORS configured to allow credentialed
cross-origin requests from the frontend during local development (the
frontend also runs its requests through a same-origin Next.js proxy, but
this API still needs to accept the proxied request and set a cookie the
browser will hold for the frontend's origin).

The existing `/auth/login`/`/auth/me` (`app/routers/auth.py`) only deal in
a bearer token returned in the JSON body, extracted via
`OAuth2PasswordBearer`. There's no way to log out (no way to clear
anything, since nothing is stored server-side or in a cookie today).

## Goals

- `/auth/login` sets an httpOnly cookie carrying the JWT, in addition to
  returning it in the JSON body (existing behavior/tests for the body are
  preserved).
- `/auth/me` accepts the token from either the cookie or the
  `Authorization: Bearer` header (cookie takes priority) — the header
  path stays so the API remains easy to exercise with `curl`/tests
  without cookie-jar plumbing.
- A new `POST /auth/logout` clears the cookie.
- CORS allows the configured frontend origin, with credentials.

## Non-goals

- Refresh tokens — out of scope, same as the original auth spec.
- Verifying the JWT anywhere outside this API (the frontend's Next.js
  middleware only checks whether the cookie is *present*, not valid —
  that's a frontend-repo decision, not this API's concern).
- CSRF protection beyond `SameSite=Lax` — acceptable for a `Lax` cookie
  used only for `GET`-driven navigation checks and same-site `fetch`
  calls in local dev; revisit if this ever serves a different site.

## Design

**Settings (`app/core/config.py`)** gains two fields:
- `frontend_origin: str` — e.g. `http://localhost:3000`, used for CORS.
- `cookie_secure: bool = False` — whether the cookie gets the `Secure`
  flag. Defaults to `False` for local `http://` development;
  `.env.example` documents setting it `True` behind HTTPS.

**CORS (`app/main.py`)**: `CORSMiddleware` with
`allow_origins=[settings.frontend_origin]`, `allow_credentials=True`,
`allow_methods=["*"]`, `allow_headers=["*"]`.

**Cookie**: name `access_token`, `httponly=True`,
`secure=settings.cookie_secure`, `samesite="lax"`, `path="/"`,
`max_age=settings.jwt_expire_minutes * 60`. Set on `/auth/login` via a
`Response` parameter FastAPI injects into the endpoint. Cleared on
`/auth/logout` via `response.delete_cookie("access_token", path="/")`.

**Token extraction (`app/routers/auth.py`)**: replace the
`OAuth2PasswordBearer`-only dependency with one that checks
`request.cookies.get("access_token")` first, falling back to parsing an
`Authorization: Bearer <token>` header, raising 401 if neither is
present. `get_current_user` (used by `/auth/me`) depends on this instead
of the raw bearer scheme.

**New endpoint**: `POST /auth/logout` — no request body, clears the
cookie, returns `{"detail": "logged out"}`.

## Testing plan

Extend `tests/test_auth.py`:
- Login response has a `Set-Cookie` header for `access_token` that is
  `HttpOnly`.
- `GET /auth/me` succeeds using only the cookie set by a prior login on
  the same `httpx.AsyncClient` (its cookie jar carries it automatically —
  no `Authorization` header passed).
- `GET /auth/me` still succeeds via the `Authorization: Bearer` header
  alone (no cookie), for parity with the existing tests.
- `POST /auth/logout` clears the cookie, and a subsequent `GET /auth/me`
  with no header and the (now-cleared) cookie jar returns 401.

## Repo/setup notes

- `.env.example` gains `FRONTEND_ORIGIN` and `COOKIE_SECURE`.
- After implementation, re-run the `init` skill to refresh `CLAUDE.md`
  for the new cookie/CORS behavior.
