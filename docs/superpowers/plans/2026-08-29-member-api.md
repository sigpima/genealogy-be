# Member API Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `Member` model and CRUD API (one shared family tree, no per-user ownership) so `genealogy-web` can eventually read/write real genealogy data instead of a bundled static JSON file, plus a one-off script to load the existing tree data into the database.

**Architecture:** A single self-referencing `Member` table (`parent_id -> Member.id`). `GET /members/tree` recursively assembles the whole table into the `{id, name, children}` shape the frontend already expects. Cycle prevention on `PUT` walks the proposed new parent's ancestor chain; the FK's default `RESTRICT` behavior turns "delete a member with children" into a 409 for free. All endpoints require auth via the existing `get_current_user`.

**Tech Stack:** Same as the existing backend (FastAPI, SQLAlchemy async, Alembic, pytest/httpx).

**Spec:** `docs/superpowers/specs/2026-08-29-member-api-design.md`

## Global Constraints

- One shared tree, no `owner_id`/per-user scoping — per the spec's Non-goals.
- No cascading delete — deleting a member with children returns 409; the FK has no `ondelete` override, so the database itself rejects the delete via `IntegrityError`.
- `MemberUpdate` is a full replace (`full_name` + `parent_id` both required every time), not a partial patch.
- Every `/members/*` endpoint requires authentication (`Depends(get_current_user)` from `app.routers.auth`).
- `GET /members/tree` returns HTTP 200 with a JSON `null` body when there are no members yet — never 204.

---

## File Structure

```
genealogy-api/
  app/
    models/member.py                # new
    schemas/member.py                # new
    routers/member.py                 # new
    main.py                            # modified: include member router
  alembic/versions/<rev>_create_members_table.py   # new (generated)
  scripts/seed_members.py                            # new
  tests/
    conftest.py                                        # modified: enable SQLite FK enforcement
    test_member_model.py                                 # new
    test_member_schemas.py                                # new
    test_member.py                                         # new
```

---

### Task 1: Member model

**Files:**
- Create: `app/models/member.py`
- Test: `tests/test_member_model.py`

**Interfaces:**
- Produces: `Member` (`id: int`, `full_name: str`, `parent_id: int | None`, `created_at: datetime`).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_member_model.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_member_model.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.models.member'`

- [ ] **Step 3: Write the implementation**

```python
# app/models/member.py
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Member(Base):
    __tablename__ = "members"

    id: Mapped[int] = mapped_column(primary_key=True)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("members.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_member_model.py -v`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add app/models/member.py tests/test_member_model.py
git commit -m "feat: add Member model"
```

---

### Task 2: Member schemas

**Files:**
- Create: `app/schemas/member.py`
- Test: `tests/test_member_schemas.py`

**Interfaces:**
- Produces: `MemberCreate {full_name, parent_id}`, `MemberUpdate {full_name, parent_id}`, `MemberRead {id, full_name, parent_id, created_at}`, `MemberTreeNode {id, name, children: list[MemberTreeNode]}`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_member_schemas.py
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError


def test_member_create_accepts_valid_data():
    from app.schemas.member import MemberCreate

    data = MemberCreate(full_name="A B", parent_id=None)
    assert data.full_name == "A B"
    assert data.parent_id is None


def test_member_create_rejects_empty_name():
    from app.schemas.member import MemberCreate

    with pytest.raises(ValidationError):
        MemberCreate(full_name="", parent_id=None)


def test_member_read_from_attributes():
    from app.schemas.member import MemberRead

    class FakeMember:
        id = 1
        full_name = "A B"
        parent_id = None
        created_at = datetime.now(timezone.utc)

    read = MemberRead.model_validate(FakeMember())
    assert read.id == 1
    assert read.full_name == "A B"


def test_member_tree_node_nests_children():
    from app.schemas.member import MemberTreeNode

    node = MemberTreeNode(
        id=1,
        name="Root",
        children=[MemberTreeNode(id=2, name="Child", children=[])],
    )
    assert node.children[0].name == "Child"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_member_schemas.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.schemas.member'`

- [ ] **Step 3: Write the implementation**

```python
# app/schemas/member.py
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class MemberCreate(BaseModel):
    full_name: str = Field(min_length=1)
    parent_id: int | None = None


class MemberUpdate(BaseModel):
    full_name: str = Field(min_length=1)
    parent_id: int | None = None


class MemberRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    full_name: str
    parent_id: int | None
    created_at: datetime


class MemberTreeNode(BaseModel):
    id: int
    name: str
    children: list["MemberTreeNode"] = []
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_member_schemas.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add app/schemas/member.py tests/test_member_schemas.py
git commit -m "feat: add Member Pydantic schemas"
```

---

### Task 3: Member router (tree/create/update/delete)

**Files:**
- Create: `app/routers/member.py`
- Modify: `app/main.py`, `tests/conftest.py`
- Test: `tests/test_member.py`

**Interfaces:**
- Consumes: `Member` (Task 1), `MemberCreate`/`MemberUpdate`/`MemberRead`/`MemberTreeNode` (Task 2), `get_current_user` (`app/routers/auth.py`).
- Produces: `GET /members/tree`, `POST /members`, `PUT /members/{id}`, `DELETE /members/{id}`.

- [ ] **Step 1: Enable SQLite foreign-key enforcement in the test client fixture**

SQLite does not enforce foreign keys by default — without this, `test_delete_rejects_member_with_children` below would pass for the wrong reason (SQLite would silently allow the delete, and the router's `except IntegrityError` would simply never fire, but the *test* would still fail because the response would be 204, not 409 — so this must be fixed before that test can pass at all).

In `tests/conftest.py`, add `from sqlalchemy import event` to the imports, and inside the `client` fixture, right after `engine = create_async_engine("sqlite+aiosqlite:///:memory:")`, add:

```python
    @event.listens_for(engine.sync_engine, "connect")
    def _enable_sqlite_foreign_keys(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()
```

- [ ] **Step 2: Write the failing tests**

```python
# tests/test_member.py
async def _authenticate(client):
    await client.post(
        "/auth/register",
        json={
            "email": "member-tester@example.com",
            "password": "longenough",
            "full_name": "Tester",
        },
    )
    await client.post(
        "/auth/login",
        json={"email": "member-tester@example.com", "password": "longenough"},
    )


async def test_tree_is_null_when_empty(client):
    await _authenticate(client)
    response = await client.get("/members/tree")
    assert response.status_code == 200
    assert response.json() is None


async def test_create_and_fetch_tree(client):
    await _authenticate(client)
    root = await client.post("/members", json={"full_name": "Root", "parent_id": None})
    root_id = root.json()["id"]
    await client.post("/members", json={"full_name": "Child A", "parent_id": root_id})
    await client.post("/members", json={"full_name": "Child B", "parent_id": root_id})

    response = await client.get("/members/tree")
    assert response.status_code == 200
    tree = response.json()
    assert tree["name"] == "Root"
    assert {child["name"] for child in tree["children"]} == {"Child A", "Child B"}


async def test_create_rejects_nonexistent_parent(client):
    await _authenticate(client)
    response = await client.post("/members", json={"full_name": "Orphan", "parent_id": 9999})
    assert response.status_code == 404


async def test_update_full_name(client):
    await _authenticate(client)
    created = await client.post("/members", json={"full_name": "Original", "parent_id": None})
    member_id = created.json()["id"]

    response = await client.put(
        f"/members/{member_id}", json={"full_name": "Renamed", "parent_id": None}
    )
    assert response.status_code == 200
    assert response.json()["full_name"] == "Renamed"


async def test_update_rejects_self_as_parent(client):
    await _authenticate(client)
    created = await client.post("/members", json={"full_name": "Solo", "parent_id": None})
    member_id = created.json()["id"]

    response = await client.put(
        f"/members/{member_id}", json={"full_name": "Solo", "parent_id": member_id}
    )
    assert response.status_code == 400


async def test_update_rejects_descendant_as_parent(client):
    await _authenticate(client)
    root = await client.post("/members", json={"full_name": "Root", "parent_id": None})
    root_id = root.json()["id"]
    child = await client.post("/members", json={"full_name": "Child", "parent_id": root_id})
    child_id = child.json()["id"]

    response = await client.put(
        f"/members/{root_id}", json={"full_name": "Root", "parent_id": child_id}
    )
    assert response.status_code == 400


async def test_delete_leaf_member(client):
    await _authenticate(client)
    created = await client.post("/members", json={"full_name": "ToDelete", "parent_id": None})
    member_id = created.json()["id"]

    response = await client.delete(f"/members/{member_id}")
    assert response.status_code == 204

    tree_response = await client.get("/members/tree")
    assert tree_response.json() is None


async def test_delete_rejects_member_with_children(client):
    await _authenticate(client)
    root = await client.post("/members", json={"full_name": "Root", "parent_id": None})
    root_id = root.json()["id"]
    await client.post("/members", json={"full_name": "Child", "parent_id": root_id})

    response = await client.delete(f"/members/{root_id}")
    assert response.status_code == 409


async def test_member_endpoints_require_auth(client):
    response = await client.get("/members/tree")
    assert response.status_code == 401
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/test_member.py -v`
Expected: FAIL — every request 404s (no `/members` routes registered yet).

- [ ] **Step 4: Write the router**

```python
# app/routers/member.py
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.member import Member
from app.routers.auth import get_current_user
from app.schemas.member import MemberCreate, MemberRead, MemberTreeNode, MemberUpdate

router = APIRouter(
    prefix="/members", tags=["members"], dependencies=[Depends(get_current_user)]
)


def _build_tree(members: list[Member]) -> MemberTreeNode | None:
    children_by_parent: dict[int | None, list[Member]] = {}
    for member in members:
        children_by_parent.setdefault(member.parent_id, []).append(member)

    root_candidates = children_by_parent.get(None, [])
    if not root_candidates:
        return None
    root = root_candidates[0]

    def build(node: Member) -> MemberTreeNode:
        return MemberTreeNode(
            id=node.id,
            name=node.full_name,
            children=[build(child) for child in children_by_parent.get(node.id, [])],
        )

    return build(root)


async def _is_descendant(db: AsyncSession, ancestor_id: int, candidate_id: int) -> bool:
    """True if candidate_id is currently a descendant of ancestor_id."""
    current_id: int | None = candidate_id
    while current_id is not None:
        if current_id == ancestor_id:
            return True
        current = await db.get(Member, current_id)
        current_id = current.parent_id if current else None
    return False


@router.get("/tree", response_model=MemberTreeNode | None)
async def get_tree(db: AsyncSession = Depends(get_db)) -> MemberTreeNode | None:
    result = await db.execute(select(Member))
    members = list(result.scalars().all())
    return _build_tree(members)


@router.post("", response_model=MemberRead, status_code=status.HTTP_201_CREATED)
async def create_member(payload: MemberCreate, db: AsyncSession = Depends(get_db)) -> Member:
    if payload.parent_id is not None:
        parent = await db.get(Member, payload.parent_id)
        if parent is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="parent not found")

    member = Member(full_name=payload.full_name, parent_id=payload.parent_id)
    db.add(member)
    await db.commit()
    await db.refresh(member)
    return member


@router.put("/{member_id}", response_model=MemberRead)
async def update_member(
    member_id: int, payload: MemberUpdate, db: AsyncSession = Depends(get_db)
) -> Member:
    member = await db.get(Member, member_id)
    if member is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="member not found")

    if payload.parent_id is not None:
        if payload.parent_id == member_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="a member cannot be its own parent",
            )
        new_parent = await db.get(Member, payload.parent_id)
        if new_parent is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="parent not found")
        if await _is_descendant(db, member_id, payload.parent_id):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="cannot set parent to one of the member's own descendants",
            )

    member.full_name = payload.full_name
    member.parent_id = payload.parent_id
    await db.commit()
    await db.refresh(member)
    return member


@router.delete("/{member_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_member(member_id: int, db: AsyncSession = Depends(get_db)) -> None:
    member = await db.get(Member, member_id)
    if member is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="member not found")

    await db.delete(member)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="cannot delete a member who has children",
        )
```

- [ ] **Step 5: Wire the router into the app**

In `app/main.py`, add the import and registration alongside `auth_router`:

```python
from app.routers.member import router as member_router
```

and

```python
app.include_router(member_router)
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_member.py -v`
Expected: 9 passed

- [ ] **Step 7: Run the full suite to confirm nothing broke**

Run: `uv run pytest -v`
Expected: all tests pass (27 existing + 2 + 4 + 9 = 42).

- [ ] **Step 8: Commit**

```bash
git add app/routers/member.py app/main.py tests/conftest.py tests/test_member.py
git commit -m "feat: add Member CRUD + tree API"
```

---

### Task 4: Alembic migration for the `members` table

**Files:**
- Create: `alembic/versions/<rev>_create_members_table.py` (generated)

- [ ] **Step 1: Create a scratch Postgres database for migration generation/verification**

Run: `PGPASSWORD=postgres psql -U postgres -h localhost -p 5432 -c "DROP DATABASE IF EXISTS genealogy_api_migration_test;" -c "CREATE DATABASE genealogy_api_migration_test;"`

- [ ] **Step 2: Generate the migration**

Run: `DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/genealogy_api_migration_test JWT_SECRET=tmp uv run alembic revision --autogenerate -m "create members table"`
Expected: creates `alembic/versions/<rev>_create_members_table.py` containing `op.create_table("members", ...)` with columns `id`, `full_name`, `parent_id`, `created_at`, and a self-referencing FK on `parent_id`.

- [ ] **Step 3: Verify the migration applies cleanly**

Run: `DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/genealogy_api_migration_test JWT_SECRET=tmp uv run alembic upgrade head`
Expected: no errors, both `create users table` and `create members table` revisions applied in order.

- [ ] **Step 4: Verify the downgrade path works**

Run: `DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/genealogy_api_migration_test JWT_SECRET=tmp uv run alembic downgrade base`
Expected: no errors, both tables dropped.

- [ ] **Step 5: Tear down the scratch database**

Run: `PGPASSWORD=postgres psql -U postgres -h localhost -p 5432 -c "DROP DATABASE IF EXISTS genealogy_api_migration_test;"`

- [ ] **Step 6: Apply the migration to the real local dev database**

Run: `uv run alembic upgrade head` (using the project's actual `.env` `DATABASE_URL`)
Expected: `members` table now exists in the real dev database, ready for Task 5's seed script.

- [ ] **Step 7: Commit**

```bash
git add alembic/versions
git commit -m "feat: add Alembic migration for members table"
```

---

### Task 5: Seed script

**Files:**
- Create: `scripts/seed_members.py`

- [ ] **Step 1: Write the script**

```python
# scripts/seed_members.py
"""One-off script to load a {name, children} JSON tree into the members table.

Usage: uv run python scripts/seed_members.py path/to/tree.json
"""

import asyncio
import json
import sys

from app.db.session import get_session_maker
from app.models.member import Member


async def _seed(tree: dict) -> None:
    session_maker = get_session_maker()
    async with session_maker() as session:

        async def insert(node: dict, parent_id: int | None) -> None:
            member = Member(full_name=node["name"], parent_id=parent_id)
            session.add(member)
            await session.flush()
            for child in node.get("children", []):
                await insert(child, member.id)

        await insert(tree, None)
        await session.commit()


def main() -> None:
    if len(sys.argv) != 2:
        print("Usage: uv run python scripts/seed_members.py path/to/tree.json")
        raise SystemExit(1)

    with open(sys.argv[1], encoding="utf-8") as f:
        tree = json.load(f)

    asyncio.run(_seed(tree))
    print("Seed complete.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run it against the real local dev database**

Run: `uv run python scripts/seed_members.py ../genealogy-web/src/app/genealogy-tree/new_treeData.json`
Expected: `Seed complete.` with no errors.

- [ ] **Step 3: Verify the row count and root**

Run: `PGPASSWORD=postgres psql -U postgres -h localhost -p 5432 -d genealogy -c "SELECT count(*) FROM members;" -c "SELECT full_name FROM members WHERE parent_id IS NULL;"`
Expected: a count in the hundreds (matching the JSON file's node count), and exactly one row with `full_name = 'nguyễn đại lan'`.

- [ ] **Step 4: Verify via the actual API**

Start the app: `uv run uvicorn app.main:app --port 8000` (background). Register+login to get a cookie, then:

Run: `curl -s -b cookies.txt -c cookies.txt -X POST http://localhost:8000/auth/register -H "Content-Type: application/json" -d "{\"email\":\"seedcheck@example.com\",\"password\":\"longenough\",\"full_name\":\"Seed Check\"}"` then `curl -s -b cookies.txt -c cookies.txt -X POST http://localhost:8000/auth/login -H "Content-Type: application/json" -d "{\"email\":\"seedcheck@example.com\",\"password\":\"longenough\"}"` then `curl -s -b cookies.txt http://localhost:8000/members/tree | head -c 200`
Expected: JSON starting with `{"id":...,"name":"nguyễn đại lan","children":[...`

Stop the app afterward.

- [ ] **Step 5: Commit**

```bash
git add scripts/seed_members.py
git commit -m "feat: add seed script for loading tree JSON into members table"
```

---

### Task 6: Full verification + CLAUDE.md refresh

- [ ] **Step 1: Run the full test suite**

Run: `uv run pytest -v`
Expected: 42 passed.

- [ ] **Step 2: Refresh CLAUDE.md**

Invoke the `init` skill (Skill tool, `skill: "init"`) for this repository — it should document the `Member` model, the tree-building/cycle-check approach, the FK-based delete-conflict behavior, the SQLite foreign-key test gotcha, and the seed script.

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: refresh CLAUDE.md for Member API"
```

---

## Self-Review Notes

- **Spec coverage:** `Member` model ✓ (Task 1), schemas ✓ (Task 2), `GET/POST/PUT/DELETE /members*` ✓ (Task 3), auth-required ✓ (Task 3, router-level dependency), cycle prevention ✓ (Task 3), delete-conflict via FK ✓ (Task 3, requires the SQLite PRAGMA fix to be testable), migration ✓ (Task 4), seed script ✓ (Task 5), CLAUDE.md ✓ (Task 6). Non-goals (per-user ownership, extra fields, cascading delete) untouched.
- **Placeholder scan:** none — every step has literal code or an exact command with expected output.
- **Type consistency:** `Member.parent_id`/`MemberCreate.parent_id`/`MemberUpdate.parent_id` all `int | None` consistently; `_build_tree`/`_is_descendant` signatures match their call sites; `MemberTreeNode.name` (not `full_name`) matches what `_build_tree` constructs and what the tests assert on.
