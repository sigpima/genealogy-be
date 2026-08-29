from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


@pytest.fixture
async def session():
    from app.db.base import Base
    from app.models.password_reset_token import PasswordResetToken  # noqa: F401
    from app.models.user import User  # noqa: F401

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as s:
        yield s
    await engine.dispose()


async def test_create_password_reset_token(session):
    from app.models.password_reset_token import PasswordResetToken
    from app.models.user import User

    user = User(email="a@example.com", hashed_password="hashed", full_name="A B")
    session.add(user)
    await session.commit()
    await session.refresh(user)

    expires_at = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(minutes=30)
    token = PasswordResetToken(user_id=user.id, token_hash="a" * 64, expires_at=expires_at)
    session.add(token)
    await session.commit()

    result = await session.execute(
        select(PasswordResetToken).where(PasswordResetToken.user_id == user.id)
    )
    fetched = result.scalar_one()
    assert fetched.token_hash == "a" * 64
    assert fetched.used_at is None
    assert fetched.created_at is not None
