import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


@pytest.fixture
async def session():
    from app.db.base import Base
    from app.models.user import User  # noqa: F401  (registers User on Base.metadata)

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as s:
        yield s
    await engine.dispose()


async def test_create_and_query_user(session):
    from app.models.user import User

    user = User(email="a@example.com", hashed_password="hashed", full_name="A B")
    session.add(user)
    await session.commit()

    result = await session.execute(select(User).where(User.email == "a@example.com"))
    fetched = result.scalar_one()

    assert fetched.id is not None
    assert fetched.full_name == "A B"
    assert fetched.created_at is not None


async def test_email_unique_constraint(session):
    from app.models.user import User

    session.add(User(email="dup@example.com", hashed_password="h1", full_name="X"))
    await session.commit()

    session.add(User(email="dup@example.com", hashed_password="h2", full_name="Y"))
    with pytest.raises(IntegrityError):
        await session.commit()
