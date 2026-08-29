import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


@pytest.fixture
async def session():
    from app.db.base import Base
    from app.models.member import Member  # noqa: F401

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as s:
        yield s
    await engine.dispose()


async def test_create_root_member(session):
    from app.models.member import Member

    root = Member(full_name="Root")
    session.add(root)
    await session.commit()
    await session.refresh(root)

    assert root.id is not None
    assert root.parent_id is None
    assert root.created_at is not None


async def test_create_child_member(session):
    from app.models.member import Member

    root = Member(full_name="Root")
    session.add(root)
    await session.commit()
    await session.refresh(root)

    child = Member(full_name="Child", parent_id=root.id)
    session.add(child)
    await session.commit()

    result = await session.execute(select(Member).where(Member.full_name == "Child"))
    fetched = result.scalar_one()
    assert fetched.parent_id == root.id
