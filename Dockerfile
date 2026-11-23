# syntax=docker/dockerfile:1

FROM python:3.12-slim AS builder

# Pull the uv binary from its official image (pinned: the version that produced uv.lock) rather than installing via pip.
COPY --from=ghcr.io/astral-sh/uv:0.13.1 /uv /uvx /usr/local/bin/

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy

# Install dependencies first so this layer stays cached when only app code changes.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev

COPY . .
RUN uv sync --frozen --no-dev


FROM python:3.12-slim

RUN useradd --create-home --shell /usr/sbin/nologin app
WORKDIR /app

COPY --from=builder /app /app
ENV PATH="/app/.venv/bin:$PATH"

# UPLOAD_DIR defaults to "uploads" (see app/core/config.py); pre-create it here so a
# fresh container has somewhere to write avatars before the first upload.
RUN mkdir -p /app/uploads/avatars && chown -R app:app /app

USER app

EXPOSE 8000

# Applies pending Alembic migrations (idempotent - a no-op once already at head) before
# starting the server, so a fresh database is never left un-migrated on first boot.
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
