"""Test fixtures: every test runs against a real Postgres (never SQLite).

Start the throwaway database first:  docker compose up -d --wait db-test
(see docker-compose.yml). Override the target with TEST_DATABASE_URL.

- Once per session the schema is rebuilt from scratch by running the real Alembic
  migrations, so the migrations themselves are exercised too.
- Before every test all tables are TRUNCATEd (identities restart, so ids start at 1).
- Safety: the database name must end in "_test", otherwise nothing is touched.
"""

import os
import subprocess
import sys
from collections.abc import AsyncGenerator
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

PROJECT_ROOT = Path(__file__).resolve().parent.parent

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@127.0.0.1:55432/genealogy_test",
)


def _sync_url(url: str) -> str:
    return url.replace("+asyncpg", "+psycopg2")


@pytest.fixture(scope="session", autouse=True)
def _database():
    url = make_url(TEST_DATABASE_URL)
    if not (url.database or "").endswith("_test"):
        pytest.exit(
            f"Refusing to run tests on database {url.database!r}: its name must end in '_test' "
            "(tests TRUNCATE every table).",
            returncode=2,
        )

    engine = create_engine(_sync_url(TEST_DATABASE_URL), isolation_level="AUTOCOMMIT")
    try:
        with engine.connect() as connection:
            connection.execute(text("DROP SCHEMA public CASCADE"))
            connection.execute(text("CREATE SCHEMA public"))
    except OperationalError as exc:
        engine.dispose()
        pytest.exit(
            "Cannot reach the test Postgres. Start it with:\n"
            "    docker compose up -d --wait db-test\n"
            f"(tried {url.render_as_string(hide_password=True)})\n{exc.orig}",
            returncode=2,
        )

    # A subprocess keeps alembic's logging config from leaking into pytest. DATABASE_URL in the
    # environment wins over any developer .env.
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=PROJECT_ROOT,
        env={**os.environ, "DATABASE_URL": TEST_DATABASE_URL, "JWT_SECRET": "test-secret"},
        check=True,
        capture_output=True,
    )
    yield engine
    engine.dispose()


@pytest.fixture(autouse=True)
def _clean_tables(_database):
    with _database.connect() as connection:
        tables = [
            row[0]
            for row in connection.execute(
                text(
                    "SELECT tablename FROM pg_tables "
                    "WHERE schemaname = 'public' AND tablename <> 'alembic_version'"
                )
            )
        ]
        if tables:
            quoted = ", ".join(f'"{name}"' for name in tables)
            connection.execute(text(f"TRUNCATE {quoted} RESTART IDENTITY CASCADE"))
            connection.commit()


@pytest.fixture(autouse=True)
def _env(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", TEST_DATABASE_URL)
    monkeypatch.setenv("JWT_SECRET", "test-secret")
    monkeypatch.setenv("JWT_EXPIRE_MINUTES", "60")
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path))
    from app.core.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def upload_dir(tmp_path) -> Path:
    return tmp_path


@pytest.fixture
async def engine(_env):
    # NullPool: asyncpg connections are bound to the event loop, and pytest-asyncio gives every
    # test its own loop, so connections must not be pooled across tests.
    test_engine = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)
    yield test_engine
    await test_engine.dispose()


@pytest.fixture
async def session(engine) -> AsyncGenerator[AsyncSession, None]:
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as s:
        yield s


@pytest.fixture
async def client(_env, engine) -> AsyncGenerator[AsyncClient, None]:
    from app.db.session import get_db
    from app.main import app

    session_maker = async_sessionmaker(engine, expire_on_commit=False)

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        async with session_maker() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


@pytest.fixture
async def make_client(client):
    """Factory for extra, independent clients (own cookie jar) talking to the same app and DB.

    `client` itself is one logged-in/out session; use this when a test needs several people at once
    (an admin, a member and a guest).
    """
    from app.main import app

    created: list[AsyncClient] = []

    def factory() -> AsyncClient:
        extra = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
        created.append(extra)
        return extra

    yield factory
    for extra in created:
        await extra.aclose()
