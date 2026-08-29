# FastAPI Auth Backend — Design Spec

Date: 2026-08-29
Status: Approved for implementation planning

## Context

The original backend (`genealogy-legacy`, Spring Boot / Java) is being retired.
Only its auth slice (`User` entity, register/login) was ever functional; it also
shipped several security issues (hardcoded JWT secret, plaintext DB password in
`application.properties`, password hash echoed back in the register response,
no global error handling, no input validation, a broken `UserGrant` mapping).

This spec covers a from-scratch Python/FastAPI replacement, **scoped to auth
only**. Member/Family CRUD (the actual genealogy data) is an explicitly
separate follow-up spec — not built here (YAGNI: don't guess that schema
before the frontend redesign clarifies what it needs).

## Goals

- Register + login working end-to-end, issuing JWT bearer tokens.
- Fix every security issue identified in the legacy review.
- Project structure that a Member/Family phase can extend without rework.

## Non-goals

- Member/Family/Grant data model and endpoints (future spec).
- Refresh tokens, OAuth/social login, password reset flows.
- Deployment/containerization (Docker, CI) — not requested yet.

## Architecture

FastAPI app, async throughout:

- **Web framework**: FastAPI, async route handlers.
- **ORM**: SQLAlchemy 2.0 async (`asyncpg` driver against PostgreSQL).
- **Migrations**: Alembic, using a separate sync engine (`psycopg2`) purely
  for migration execution — a standard pattern since Alembic's autogenerate
  tooling is more mature on the sync path; the app itself never uses this
  engine at runtime.
- **Config**: `pydantic-settings`, reading `DATABASE_URL`, `JWT_SECRET`,
  `JWT_EXPIRE_MINUTES` from environment / `.env` (never hardcoded, never
  committed — `.env.example` documents the shape).
- **Password hashing**: `passlib[bcrypt]`.
- **JWT**: `python-jose`.
- **Testing**: `pytest` + `pytest-asyncio` + `httpx.AsyncClient`
  (`ASGITransport`) against a SQLite in-memory async engine for speed;
  no real Postgres needed for the test suite.

## Folder structure

```
genealogy-api/
  app/
    core/
      config.py      # Settings (pydantic-settings)
      security.py     # hash_password, verify_password, create_access_token, decode_access_token
    db/
      base.py         # declarative Base
      session.py      # async_engine, async_sessionmaker, get_db dependency
    models/
      user.py          # User (SQLAlchemy model)
    schemas/
      user.py          # UserCreate, UserRead (Pydantic — never expose the ORM model directly)
      auth.py          # LoginRequest, TokenResponse
    routers/
      auth.py          # POST /auth/register, POST /auth/login
    main.py            # app factory, router include, exception handlers
  alembic/
    env.py
    versions/
  tests/
    conftest.py        # async test client + in-memory DB fixture
    test_auth.py
  .env.example
  pyproject.toml
  README.md
```

## Data model (this phase)

Only `User`:

| column          | type      | notes                          |
|------------------|-----------|---------------------------------|
| id               | int PK    | auto-increment                 |
| email            | str, unique, indexed | login identifier      |
| hashed_password  | str       | bcrypt hash, never serialized  |
| full_name        | str       | camelCase-consistent naming (fixes legacy snake_case field inconsistency) |
| created_at       | datetime  | server default now             |

## API surface

- `POST /auth/register` — body: `UserCreate {email, password, full_name}` →
  response: `UserRead {id, email, full_name, created_at}` (password/hash
  never in the response — fixes the legacy leak).
- `POST /auth/login` — body: `LoginRequest {email, password}` → response:
  `TokenResponse {access_token, token_type: "bearer"}`.
- `GET /auth/me` — bearer-auth protected, returns the current `UserRead`;
  exists mainly so the frontend has something to verify a token against.

## Error handling

- Pydantic validation errors → FastAPI's default 422 (already structured JSON).
- Domain errors (duplicate email, bad credentials) raise `HTTPException` with
  a consistent `{"detail": "..."}` body.
- A single `@app.exception_handler(Exception)` catches anything unhandled and
  returns a generic 500 JSON body instead of leaking a stack trace.

## Security fixes carried from the legacy review

- JWT secret and DB URL come from environment variables only; `.env` is
  gitignored, `.env.example` provided with placeholder values.
- Register/login responses never include `hashed_password`.
- All input validated via Pydantic schemas (legacy had none).
- No dead/unused security scaffolding (legacy had an unused
  `CustomUserDetails` class and an empty `MemberController`) — this rewrite
  only contains code that's wired up and used.

## Testing plan

- `test_auth.py`: register success, register duplicate email (409), login
  success, login wrong password (401), `GET /auth/me` with/without valid
  token.
- `security.py` unit tests: hash/verify roundtrip, token create/decode,
  expired-token rejection.

## Repo/setup notes

- `git init` already done in `genealogy-api/`; this spec is the first commit.
- Legacy Java project preserved at `../genealogy-legacy` for reference only,
  not touched further.
- After implementation, run the `init` skill to generate `CLAUDE.md` for this
  repo documenting the actual resulting structure.
