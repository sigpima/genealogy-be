# genealogy-api

Async FastAPI backend for the genealogy app — auth only in this phase
(register/login/me). Member/Family CRUD is a future phase (see
`docs/superpowers/specs/`).

## Setup

    uv sync
    cp .env.example .env   # edit JWT_SECRET and DATABASE_URL for your machine

## Run

    uv run uvicorn app.main:app --reload

## Test

    uv run pytest

## Migrations

    uv run alembic upgrade head          # apply migrations
    uv run alembic revision --autogenerate -m "message"   # create a new one
