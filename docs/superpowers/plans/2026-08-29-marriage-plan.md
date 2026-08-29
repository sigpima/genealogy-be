# Marriage (Spouse Relationships) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a member of the shared family tree have one or more recorded marriages over time; each spouse is a full `Member` record (not part of the blood-line tree) shown only in the frontend's member detail panel.

**Architecture:** New `marriages` table (`member_id`, `spouse_id` both FK → `members.id` with `ON DELETE CASCADE`, `marriage_year`). `GET /members/tree`'s `_build_tree` excludes spouse ids from root candidates and attaches each member's spouses as a `spouses` list on their tree node. New `POST /members/{member_id}/marriages` and `PUT /members/marriages/{marriage_id}` endpoints; deleting a spouse reuses the existing `DELETE /members/{id}` (the FK cascade removes the marriage row). Frontend: `MemberDetailPanel` gains a "Vợ/chồng" section (list, inline edit per row, add form); `genealogy-tree/page.tsx` wires the new fields and three new mutation handlers.

**Tech Stack:** FastAPI, SQLAlchemy 2.0 async, Pydantic v2, Alembic, pytest/pytest-asyncio/httpx (backend, `genealogy-api/`); Next.js 15, React 19, TypeScript (frontend, `genealogy-web/`).

**Spec:** `docs/superpowers/specs/2026-08-29-marriage-design.md`

## Global Constraints

- A spouse is always created together with its marriage (no flow to marry two pre-existing tree members to each other).
- A spouse `Member` always has `parent_id = NULL` and is never expected to have children of its own.
- A member can have multiple marriages over time (remarriage) — `spouses` is a list, not a single optional field.
- Children keep a single `parent_id` — this feature does not add a second parent to `Member`.
- No new router file, no new auth wiring — marriage routes live in the existing `app/routers/member.py` and inherit its router-level `get_current_user` dependency.
- Frontend UI changes in this codebase are verified via `tsc --noEmit` + `eslint` + `vitest run` + a real-browser Playwright pass, not per-component unit tests (see `genealogy-web/CLAUDE.md`'s Testing section) — follow that established convention rather than inventing component tests.
- Both repos are plain `main`-branch checkouts with no remote configured — commit directly to `main` in each repo per task; do not create branches or attempt to push.

---

### Task 1: `Marriage` model and migration

**Files:**
- Create: `genealogy-api/app/models/marriage.py`
- Modify: `genealogy-api/alembic/env.py:13`
- Test: `genealogy-api/tests/test_marriage_model.py`

**Interfaces:**
- Produces: `Marriage` class (`app/models/marriage.py`) with `id: int`, `member_id: int`, `spouse_id: int`, `marriage_year: int | None`, `created_at: datetime` — consumed by Task 3 (routers) and Task 4 (`_build_tree`).

- [ ] **Step 1: Write the failing test**

Create `genealogy-api/tests/test_marriage_model.py`:

```python
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


@pytest.fixture
async def session():
    from app.db.base import Base
    from app.models.marriage import Marriage  # noqa: F401
    from app.models.member import Member  # noqa: F401

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as s:
        yield s
    await engine.dispose()


async def test_create_marriage(session):
    from app.models.marriage import Marriage
    from app.models.member import Member

    husband = Member(full_name="Husband")
    wife = Member(full_name="Wife")
    session.add_all([husband, wife])
    await session.commit()
    await session.refresh(husband)
    await session.refresh(wife)

    marriage = Marriage(member_id=husband.id, spouse_id=wife.id, marriage_year=1975)
    session.add(marriage)
    await session.commit()

    result = await session.execute(select(Marriage).where(Marriage.member_id == husband.id))
    fetched = result.scalar_one()
    assert fetched.spouse_id == wife.id
    assert fetched.marriage_year == 1975
    assert fetched.created_at is not None


async def test_create_marriage_without_year_defaults_to_none(session):
    from app.models.marriage import Marriage
    from app.models.member import Member

    husband = Member(full_name="Husband")
    wife = Member(full_name="Wife")
    session.add_all([husband, wife])
    await session.commit()
    await session.refresh(husband)
    await session.refresh(wife)

    marriage = Marriage(member_id=husband.id, spouse_id=wife.id)
    session.add(marriage)
    await session.commit()
    await session.refresh(marriage)

    assert marriage.marriage_year is None
```

- [ ] **Step 2: Run the test to verify it fails**

Run (from `genealogy-api/`): `uv run pytest tests/test_marriage_model.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.models.marriage'`

- [ ] **Step 3: Write the model**

Create `genealogy-api/app/models/marriage.py`:

```python
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Marriage(Base):
    __tablename__ = "marriages"

    id: Mapped[int] = mapped_column(primary_key=True)
    member_id: Mapped[int] = mapped_column(
        ForeignKey("members.id", ondelete="CASCADE"), nullable=False
    )
    spouse_id: Mapped[int] = mapped_column(
        ForeignKey("members.id", ondelete="CASCADE"), nullable=False
    )
    marriage_year: Mapped[int | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
```

Modify `genealogy-api/alembic/env.py` line 13 from:
```python
from app.models import member, user  # noqa: E402,F401  (registers models on Base.metadata)
```
to:
```python
from app.models import marriage, member, user  # noqa: E402,F401  (registers models on Base.metadata)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/test_marriage_model.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Generate and apply the Alembic migration**

Requires a live Postgres reachable via `DATABASE_URL` (the local `postgresql-x64-18` Windows service, same as every prior migration in this project — see `genealogy-api/CLAUDE.md`), already at `head`.

Run: `uv run alembic revision --autogenerate -m "add marriages table"`

Open the generated file under `genealogy-api/alembic/versions/` and confirm `upgrade()` contains an `op.create_table('marriages', ...)` with:
- `sa.Column('member_id', sa.Integer(), nullable=False)`
- `sa.Column('spouse_id', sa.Integer(), nullable=False)`
- `sa.Column('marriage_year', sa.Integer(), nullable=True)`
- `sa.ForeignKeyConstraint(['member_id'], ['members.id'], ondelete='CASCADE')`
- `sa.ForeignKeyConstraint(['spouse_id'], ['members.id'], ondelete='CASCADE')`

If any `ondelete='CASCADE'` is missing from the autogenerated file, add it by hand before proceeding — Alembic's autogenerate reliably detects the FK but occasionally needs the `ondelete` kwarg confirmed against the model.

Run: `uv run alembic upgrade head`
Expected: migration applies with no errors.

- [ ] **Step 6: Commit**

```bash
git add app/models/marriage.py alembic/env.py alembic/versions/ tests/test_marriage_model.py
git commit -m "feat: add Marriage model and migration"
```

---

### Task 2: Marriage schemas

**Files:**
- Modify: `genealogy-api/app/schemas/member.py`
- Test: `genealogy-api/tests/test_marriage_schemas.py`

**Interfaces:**
- Consumes: `Gender` enum already defined in `app/schemas/member.py`.
- Produces: `MarriageCreate`, `MarriageUpdate`, `SpouseInfo` (all in `app/schemas/member.py`) and `MemberTreeNode.spouses: list[SpouseInfo]` — consumed by Task 3 (routers) and Task 4 (`_build_tree`).

- [ ] **Step 1: Write the failing test**

Create `genealogy-api/tests/test_marriage_schemas.py`:

```python
import pytest
from pydantic import ValidationError

from app.schemas.member import MarriageCreate, MarriageUpdate, SpouseInfo


def test_marriage_create_defaults():
    payload = MarriageCreate(spouse_full_name="Wife")
    assert payload.marriage_year is None
    assert payload.spouse_gender is None
    assert payload.spouse_birth_year is None


def test_marriage_create_rejects_death_before_birth():
    with pytest.raises(ValidationError):
        MarriageCreate(spouse_full_name="Wife", spouse_birth_year=2000, spouse_death_year=1990)


def test_marriage_create_rejects_blank_name():
    with pytest.raises(ValidationError):
        MarriageCreate(spouse_full_name="")


def test_marriage_update_rejects_death_before_birth():
    with pytest.raises(ValidationError):
        MarriageUpdate(spouse_full_name="Wife", spouse_birth_year=2000, spouse_death_year=1990)


def test_spouse_info_roundtrip():
    info = SpouseInfo(
        marriage_id=1,
        marriage_year=1975,
        id=2,
        full_name="Wife",
        birth_year=1950,
        death_year=None,
        gender="female",
        notes=None,
    )
    assert info.full_name == "Wife"
    assert info.gender == "female"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_marriage_schemas.py -v`
Expected: FAIL with `ImportError: cannot import name 'MarriageCreate' from 'app.schemas.member'`

- [ ] **Step 3: Write the schemas**

In `genealogy-api/app/schemas/member.py`, insert the following after the `MemberUpdate` class (i.e. between `MemberUpdate` and `MemberRead`):

```python
class MarriageCreate(BaseModel):
    spouse_full_name: str = Field(min_length=1)
    spouse_birth_year: int | None = None
    spouse_death_year: int | None = None
    spouse_gender: Gender | None = None
    spouse_notes: str | None = None
    marriage_year: int | None = None

    @model_validator(mode="after")
    def _check_years(self) -> "MarriageCreate":
        if (
            self.spouse_birth_year is not None
            and self.spouse_death_year is not None
            and self.spouse_death_year < self.spouse_birth_year
        ):
            raise ValueError("spouse_death_year cannot be before spouse_birth_year")
        return self


class MarriageUpdate(BaseModel):
    spouse_full_name: str = Field(min_length=1)
    spouse_birth_year: int | None = None
    spouse_death_year: int | None = None
    spouse_gender: Gender | None = None
    spouse_notes: str | None = None
    marriage_year: int | None = None

    @model_validator(mode="after")
    def _check_years(self) -> "MarriageUpdate":
        if (
            self.spouse_birth_year is not None
            and self.spouse_death_year is not None
            and self.spouse_death_year < self.spouse_birth_year
        ):
            raise ValueError("spouse_death_year cannot be before spouse_birth_year")
        return self


class SpouseInfo(BaseModel):
    marriage_id: int
    marriage_year: int | None = None
    id: int
    full_name: str
    birth_year: int | None = None
    death_year: int | None = None
    gender: Gender | None = None
    notes: str | None = None
```

Then modify the existing `MemberTreeNode` class to add the `spouses` field (after `notes`, before `children`):

```python
class MemberTreeNode(BaseModel):
    id: int
    name: str
    birth_year: int | None = None
    death_year: int | None = None
    gender: Gender | None = None
    notes: str | None = None
    spouses: list[SpouseInfo] = []
    children: list["MemberTreeNode"] = []
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_marriage_schemas.py -v`
Expected: PASS (5 tests)

Run: `uv run pytest tests/test_member_schemas.py -v`
Expected: still PASS (confirms `MemberTreeNode`'s new field with a default doesn't break existing construction).

- [ ] **Step 5: Commit**

```bash
git add app/schemas/member.py tests/test_marriage_schemas.py
git commit -m "feat: add marriage schemas and MemberTreeNode.spouses"
```

---

### Task 3: `POST /members/{member_id}/marriages` and `PUT /members/marriages/{marriage_id}`

**Files:**
- Modify: `genealogy-api/app/routers/member.py`
- Test: `genealogy-api/tests/test_marriage.py`

**Interfaces:**
- Consumes: `Marriage` (Task 1), `MarriageCreate`/`MarriageUpdate`/`SpouseInfo` (Task 2).
- Produces: `_spouse_info(marriage: Marriage, spouse: Member) -> SpouseInfo` helper — consumed by Task 4's `_build_tree`.

- [ ] **Step 1: Write the failing tests**

Create `genealogy-api/tests/test_marriage.py`:

```python
async def _authenticate(client):
    await client.post(
        "/auth/register",
        json={
            "email": "marriage-tester@example.com",
            "password": "longenough",
            "full_name": "Tester",
        },
    )
    await client.post(
        "/auth/login",
        json={"email": "marriage-tester@example.com", "password": "longenough"},
    )


async def test_create_marriage(client):
    await _authenticate(client)
    root = await client.post("/members", json={"full_name": "Husband", "parent_id": None})
    root_id = root.json()["id"]

    response = await client.post(
        f"/members/{root_id}/marriages",
        json={"spouse_full_name": "Wife", "marriage_year": 1975},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["full_name"] == "Wife"
    assert body["marriage_year"] == 1975
    assert "marriage_id" in body


async def test_create_marriage_rejects_nonexistent_member(client):
    await _authenticate(client)
    response = await client.post("/members/9999/marriages", json={"spouse_full_name": "Wife"})
    assert response.status_code == 404


async def test_create_marriage_rejects_death_before_birth(client):
    await _authenticate(client)
    root = await client.post("/members", json={"full_name": "Husband", "parent_id": None})
    root_id = root.json()["id"]

    response = await client.post(
        f"/members/{root_id}/marriages",
        json={"spouse_full_name": "Wife", "spouse_birth_year": 2000, "spouse_death_year": 1990},
    )
    assert response.status_code == 422


async def test_update_marriage(client):
    await _authenticate(client)
    root = await client.post("/members", json={"full_name": "Husband", "parent_id": None})
    root_id = root.json()["id"]
    created = await client.post(f"/members/{root_id}/marriages", json={"spouse_full_name": "Wife"})
    marriage_id = created.json()["marriage_id"]

    response = await client.put(
        f"/members/marriages/{marriage_id}",
        json={
            "spouse_full_name": "Wife Updated",
            "spouse_birth_year": 1950,
            "spouse_death_year": 2020,
            "spouse_gender": "female",
            "spouse_notes": "some notes",
            "marriage_year": 1976,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["full_name"] == "Wife Updated"
    assert body["birth_year"] == 1950
    assert body["marriage_year"] == 1976


async def test_update_marriage_rejects_nonexistent_marriage(client):
    await _authenticate(client)
    response = await client.put("/members/marriages/9999", json={"spouse_full_name": "Wife"})
    assert response.status_code == 404


async def test_marriage_endpoints_require_auth(client):
    response = await client.post("/members/1/marriages", json={"spouse_full_name": "Wife"})
    assert response.status_code == 401
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_marriage.py -v`
Expected: FAIL — `404 Not Found` for the new routes (they don't exist yet), causing assertion failures on `response.status_code`.

- [ ] **Step 3: Write the endpoints**

In `genealogy-api/app/routers/member.py`, change the import block at the top from:

```python
from app.db.session import get_db
from app.models.member import Member
from app.routers.auth import get_current_user
from app.schemas.member import MemberCreate, MemberRead, MemberTreeNode, MemberUpdate
```

to:

```python
from app.db.session import get_db
from app.models.marriage import Marriage
from app.models.member import Member
from app.routers.auth import get_current_user
from app.schemas.member import (
    MarriageCreate,
    MarriageUpdate,
    MemberCreate,
    MemberRead,
    MemberTreeNode,
    MemberUpdate,
    SpouseInfo,
)
```

Then add this helper right after the `router = APIRouter(...)` block (before `_build_tree`):

```python
def _spouse_info(marriage: Marriage, spouse: Member) -> SpouseInfo:
    return SpouseInfo(
        marriage_id=marriage.id,
        marriage_year=marriage.marriage_year,
        id=spouse.id,
        full_name=spouse.full_name,
        birth_year=spouse.birth_year,
        death_year=spouse.death_year,
        gender=spouse.gender,
        notes=spouse.notes,
    )
```

Then add these two endpoints at the end of the file (after `delete_member`):

```python
@router.post(
    "/{member_id}/marriages", response_model=SpouseInfo, status_code=status.HTTP_201_CREATED
)
async def create_marriage(
    member_id: int, payload: MarriageCreate, db: AsyncSession = Depends(get_db)
) -> SpouseInfo:
    member = await db.get(Member, member_id)
    if member is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="member not found")

    spouse = Member(
        full_name=payload.spouse_full_name,
        parent_id=None,
        birth_year=payload.spouse_birth_year,
        death_year=payload.spouse_death_year,
        gender=payload.spouse_gender.value if payload.spouse_gender is not None else None,
        notes=payload.spouse_notes,
    )
    db.add(spouse)
    await db.flush()

    marriage = Marriage(member_id=member_id, spouse_id=spouse.id, marriage_year=payload.marriage_year)
    db.add(marriage)
    await db.commit()
    await db.refresh(spouse)
    await db.refresh(marriage)
    return _spouse_info(marriage, spouse)


@router.put("/marriages/{marriage_id}", response_model=SpouseInfo)
async def update_marriage(
    marriage_id: int, payload: MarriageUpdate, db: AsyncSession = Depends(get_db)
) -> SpouseInfo:
    marriage = await db.get(Marriage, marriage_id)
    if marriage is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="marriage not found")

    spouse = await db.get(Member, marriage.spouse_id)
    marriage.marriage_year = payload.marriage_year
    spouse.full_name = payload.spouse_full_name
    spouse.birth_year = payload.spouse_birth_year
    spouse.death_year = payload.spouse_death_year
    spouse.gender = payload.spouse_gender.value if payload.spouse_gender is not None else None
    spouse.notes = payload.spouse_notes
    await db.commit()
    await db.refresh(spouse)
    await db.refresh(marriage)
    return _spouse_info(marriage, spouse)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_marriage.py -v`
Expected: PASS (6 tests)

Run: `uv run pytest`
Expected: full suite still passes (no regressions in existing member/auth tests).

- [ ] **Step 5: Commit**

```bash
git add app/routers/member.py tests/test_marriage.py
git commit -m "feat: add marriage create/update endpoints"
```

---

### Task 4: Attach spouses to `GET /members/tree` and exclude them from root selection

**Files:**
- Modify: `genealogy-api/app/routers/member.py`
- Modify: `genealogy-api/tests/test_marriage.py`

**Interfaces:**
- Consumes: `_spouse_info` (Task 3), `Marriage` (Task 1).

- [ ] **Step 1: Write the failing tests**

Append to `genealogy-api/tests/test_marriage.py`:

```python
async def test_tree_includes_spouse_on_correct_node(client):
    await _authenticate(client)
    root = await client.post("/members", json={"full_name": "Husband", "parent_id": None})
    root_id = root.json()["id"]
    await client.post("/members", json={"full_name": "Child", "parent_id": root_id})
    await client.post(
        f"/members/{root_id}/marriages",
        json={"spouse_full_name": "Wife", "marriage_year": 1975},
    )

    response = await client.get("/members/tree")
    tree = response.json()
    assert tree["name"] == "Husband"
    assert len(tree["spouses"]) == 1
    assert tree["spouses"][0]["full_name"] == "Wife"
    assert tree["spouses"][0]["marriage_year"] == 1975
    assert len(tree["children"]) == 1
    assert tree["children"][0]["name"] == "Child"


async def test_tree_supports_multiple_marriages(client):
    await _authenticate(client)
    root = await client.post("/members", json={"full_name": "Husband", "parent_id": None})
    root_id = root.json()["id"]
    await client.post(f"/members/{root_id}/marriages", json={"spouse_full_name": "First Wife"})
    await client.post(f"/members/{root_id}/marriages", json={"spouse_full_name": "Second Wife"})

    response = await client.get("/members/tree")
    tree = response.json()
    names = {spouse["full_name"] for spouse in tree["spouses"]}
    assert names == {"First Wife", "Second Wife"}


async def test_deleting_spouse_removes_marriage(client):
    await _authenticate(client)
    root = await client.post("/members", json={"full_name": "Husband", "parent_id": None})
    root_id = root.json()["id"]
    created = await client.post(f"/members/{root_id}/marriages", json={"spouse_full_name": "Wife"})
    spouse_id = created.json()["id"]

    delete_response = await client.delete(f"/members/{spouse_id}")
    assert delete_response.status_code == 204

    tree_response = await client.get("/members/tree")
    tree = tree_response.json()
    assert tree["spouses"] == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_marriage.py -v`
Expected: FAIL — `tree["spouses"]` raises `KeyError` (field doesn't exist yet on the response), and the multi-root ambiguity isn't yet handled.

- [ ] **Step 3: Update `_build_tree` and `get_tree`**

In `genealogy-api/app/routers/member.py`, replace the existing `_build_tree` function:

```python
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
            birth_year=node.birth_year,
            death_year=node.death_year,
            gender=node.gender,
            notes=node.notes,
            children=[build(child) for child in children_by_parent.get(node.id, [])],
        )

    return build(root)
```

with:

```python
def _build_tree(members: list[Member], marriages: list[Marriage]) -> MemberTreeNode | None:
    spouse_ids = {marriage.spouse_id for marriage in marriages}
    marriages_by_member: dict[int, list[Marriage]] = {}
    for marriage in marriages:
        marriages_by_member.setdefault(marriage.member_id, []).append(marriage)
    members_by_id = {member.id: member for member in members}

    children_by_parent: dict[int | None, list[Member]] = {}
    for member in members:
        children_by_parent.setdefault(member.parent_id, []).append(member)

    root_candidates = [
        member for member in children_by_parent.get(None, []) if member.id not in spouse_ids
    ]
    if not root_candidates:
        return None
    root = root_candidates[0]

    def build(node: Member) -> MemberTreeNode:
        spouses = [
            _spouse_info(marriage, members_by_id[marriage.spouse_id])
            for marriage in marriages_by_member.get(node.id, [])
        ]
        return MemberTreeNode(
            id=node.id,
            name=node.full_name,
            birth_year=node.birth_year,
            death_year=node.death_year,
            gender=node.gender,
            notes=node.notes,
            spouses=spouses,
            children=[build(child) for child in children_by_parent.get(node.id, [])],
        )

    return build(root)
```

Then replace the `get_tree` endpoint:

```python
@router.get("/tree", response_model=MemberTreeNode | None)
async def get_tree(db: AsyncSession = Depends(get_db)) -> MemberTreeNode | None:
    result = await db.execute(select(Member))
    members = list(result.scalars().all())
    return _build_tree(members)
```

with:

```python
@router.get("/tree", response_model=MemberTreeNode | None)
async def get_tree(db: AsyncSession = Depends(get_db)) -> MemberTreeNode | None:
    members_result = await db.execute(select(Member))
    members = list(members_result.scalars().all())
    marriages_result = await db.execute(select(Marriage))
    marriages = list(marriages_result.scalars().all())
    return _build_tree(members, marriages)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_marriage.py -v`
Expected: PASS (9 tests total in this file)

Run: `uv run pytest`
Expected: full suite passes, including the pre-existing `tests/test_member.py::test_tree_is_null_when_empty` and `test_create_and_fetch_tree` (confirms the root-selection change doesn't break the no-spouse case).

- [ ] **Step 5: Commit**

```bash
git add app/routers/member.py tests/test_marriage.py
git commit -m "feat: attach spouses to the tree and exclude them from root selection"
```

---

### Task 5: Frontend `Spouse` type

**Files:**
- Modify: `genealogy-web/src/lib/tree/types.ts`

**Interfaces:**
- Produces: `Spouse` type — consumed by Task 6 (`MemberDetailPanel` props) and Task 7 (`page.tsx`).

- [ ] **Step 1: Update the type file**

Replace the full contents of `genealogy-web/src/lib/tree/types.ts` with:

```ts
export type Gender = 'male' | 'female' | 'other';

export type Spouse = {
  marriage_id: number;
  marriage_year: number | null;
  id: number;
  full_name: string;
  birth_year: number | null;
  death_year: number | null;
  gender: Gender | null;
  notes: string | null;
};

export type FamilyMember = {
  id?: number;
  name: string;
  birth_year?: number | null;
  death_year?: number | null;
  gender?: Gender | null;
  notes?: string | null;
  spouses?: Spouse[];
  children?: FamilyMember[];
};
```

- [ ] **Step 2: Verify no regressions**

Run (from `genealogy-web/`): `npx vitest run`
Expected: PASS (14 tests) — `spouses` is optional, so existing `FamilyMember` literals in `src/lib/tree/search.test.ts` remain valid without changes.

Run: `npx tsc --noEmit`
Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add src/lib/tree/types.ts
git commit -m "feat: add Spouse type to FamilyMember"
```

---

### Task 6: `MemberDetailPanel` spouses UI

**Files:**
- Modify: `genealogy-web/src/components/tree/MemberDetailPanel.tsx`

**Interfaces:**
- Consumes: `Gender` (from `@/lib/tree/types`).
- Produces: `PanelSpouse`, `SpouseAddInput`, `SpouseUpdateInput` types, and new `MemberDetailPanelProps` fields `spouses`, `onAddSpouse`, `onUpdateSpouse`, `onDeleteSpouse` — consumed by Task 7.

- [ ] **Step 1: Replace the file**

Replace the full contents of `genealogy-web/src/components/tree/MemberDetailPanel.tsx` with:

```tsx
'use client';

import { useState } from 'react';
import type { Gender } from '@/lib/tree/types';

export type MemberDetailPanelChild = {
  name: string;
  onSelect: () => void;
};

export type MutationResult = { ok: boolean; error?: string };

export type MemberUpdateInput = {
  name: string;
  birthYear: number | null;
  deathYear: number | null;
  gender: Gender | null;
  notes: string | null;
};

export type PanelSpouse = {
  marriageId: number;
  spouseId: number;
  name: string;
  birthYear: number | null;
  deathYear: number | null;
  gender: Gender | null;
  notes: string | null;
  marriageYear: number | null;
};

export type SpouseAddInput = {
  name: string;
  marriageYear: number | null;
};

export type SpouseUpdateInput = {
  name: string;
  birthYear: number | null;
  deathYear: number | null;
  gender: Gender | null;
  notes: string | null;
  marriageYear: number | null;
};

export type MemberDetailPanelProps = {
  name: string;
  generation: number;
  ancestorPath: string[];
  birthYear: number | null;
  deathYear: number | null;
  gender: Gender | null;
  notes: string | null;
  childMembers: MemberDetailPanelChild[];
  spouses: PanelSpouse[];
  onClose: () => void;
  onUpdate: (input: MemberUpdateInput) => Promise<MutationResult>;
  onAddChild: (name: string) => Promise<MutationResult>;
  onDelete: () => Promise<MutationResult>;
  onAddSpouse: (input: SpouseAddInput) => Promise<MutationResult>;
  onUpdateSpouse: (marriageId: number, input: SpouseUpdateInput) => Promise<MutationResult>;
  onDeleteSpouse: (spouseId: number) => Promise<MutationResult>;
};

const GENDER_LABELS: Record<Gender, string> = {
  male: 'Nam',
  female: 'Nữ',
  other: 'Khác',
};

function toInputValue(value: number | null): string {
  return value === null ? '' : String(value);
}

function parseYear(value: string): number | null {
  if (!value.trim()) return null;
  const parsed = Number(value);
  return Number.isNaN(parsed) ? null : parsed;
}

function lifespanOf(birthYear: number | null, deathYear: number | null): string | null {
  if (birthYear === null && deathYear === null) return null;
  return `${birthYear ?? '?'} – ${deathYear ?? 'nay'}`;
}

type SpouseDraft = {
  name: string;
  birthYear: string;
  deathYear: string;
  gender: string;
  notes: string;
  marriageYear: string;
};

function draftFromSpouse(spouse: PanelSpouse): SpouseDraft {
  return {
    name: spouse.name,
    birthYear: toInputValue(spouse.birthYear),
    deathYear: toInputValue(spouse.deathYear),
    gender: spouse.gender ?? '',
    marriageYear: toInputValue(spouse.marriageYear),
    notes: spouse.notes ?? '',
  };
}

export function MemberDetailPanel({
  name,
  generation,
  ancestorPath,
  birthYear,
  deathYear,
  gender,
  notes,
  childMembers,
  spouses,
  onClose,
  onUpdate,
  onAddChild,
  onDelete,
  onAddSpouse,
  onUpdateSpouse,
  onDeleteSpouse,
}: MemberDetailPanelProps) {
  const ancestors = ancestorPath.slice(0, -1);

  const [isEditing, setIsEditing] = useState(false);
  const [editedName, setEditedName] = useState(name);
  const [editedBirthYear, setEditedBirthYear] = useState(toInputValue(birthYear));
  const [editedDeathYear, setEditedDeathYear] = useState(toInputValue(deathYear));
  const [editedGender, setEditedGender] = useState<string>(gender ?? '');
  const [editedNotes, setEditedNotes] = useState(notes ?? '');
  const [newChildName, setNewChildName] = useState('');
  const [actionError, setActionError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const [editingSpouseId, setEditingSpouseId] = useState<number | null>(null);
  const [spouseDraft, setSpouseDraft] = useState<SpouseDraft | null>(null);
  const [newSpouseName, setNewSpouseName] = useState('');
  const [newSpouseMarriageYear, setNewSpouseMarriageYear] = useState('');

  function startEditing() {
    setEditedName(name);
    setEditedBirthYear(toInputValue(birthYear));
    setEditedDeathYear(toInputValue(deathYear));
    setEditedGender(gender ?? '');
    setEditedNotes(notes ?? '');
    setIsEditing(true);
  }

  async function handleSave() {
    if (!editedName.trim()) return;
    setIsSubmitting(true);
    setActionError(null);
    const result = await onUpdate({
      name: editedName.trim(),
      birthYear: parseYear(editedBirthYear),
      deathYear: parseYear(editedDeathYear),
      gender: editedGender ? (editedGender as Gender) : null,
      notes: editedNotes.trim() ? editedNotes.trim() : null,
    });
    setIsSubmitting(false);
    if (result.ok) {
      setIsEditing(false);
    } else {
      setActionError(result.error ?? 'Không thể lưu. Vui lòng thử lại.');
    }
  }

  async function handleAddChild() {
    if (!newChildName.trim()) return;
    setIsSubmitting(true);
    setActionError(null);
    const result = await onAddChild(newChildName.trim());
    setIsSubmitting(false);
    if (result.ok) {
      setNewChildName('');
    } else {
      setActionError(result.error ?? 'Không thể thêm. Vui lòng thử lại.');
    }
  }

  async function handleDelete() {
    if (!window.confirm(`Xoá "${name}"? Hành động này không thể hoàn tác.`)) return;
    setIsSubmitting(true);
    setActionError(null);
    const result = await onDelete();
    setIsSubmitting(false);
    if (!result.ok) {
      setActionError(result.error ?? 'Không thể xoá. Vui lòng thử lại.');
    }
  }

  function startEditingSpouse(spouse: PanelSpouse) {
    setEditingSpouseId(spouse.marriageId);
    setSpouseDraft(draftFromSpouse(spouse));
  }

  async function handleSaveSpouse(marriageId: number) {
    if (!spouseDraft || !spouseDraft.name.trim()) return;
    setIsSubmitting(true);
    setActionError(null);
    const result = await onUpdateSpouse(marriageId, {
      name: spouseDraft.name.trim(),
      birthYear: parseYear(spouseDraft.birthYear),
      deathYear: parseYear(spouseDraft.deathYear),
      gender: spouseDraft.gender ? (spouseDraft.gender as Gender) : null,
      notes: spouseDraft.notes.trim() ? spouseDraft.notes.trim() : null,
      marriageYear: parseYear(spouseDraft.marriageYear),
    });
    setIsSubmitting(false);
    if (result.ok) {
      setEditingSpouseId(null);
      setSpouseDraft(null);
    } else {
      setActionError(result.error ?? 'Không thể lưu. Vui lòng thử lại.');
    }
  }

  async function handleDeleteSpouse(spouse: PanelSpouse) {
    if (!window.confirm(`Xoá "${spouse.name}" khỏi danh sách vợ/chồng?`)) return;
    setIsSubmitting(true);
    setActionError(null);
    const result = await onDeleteSpouse(spouse.spouseId);
    setIsSubmitting(false);
    if (!result.ok) {
      setActionError(result.error ?? 'Không thể xoá. Vui lòng thử lại.');
    }
  }

  async function handleAddSpouse() {
    if (!newSpouseName.trim()) return;
    setIsSubmitting(true);
    setActionError(null);
    const result = await onAddSpouse({
      name: newSpouseName.trim(),
      marriageYear: parseYear(newSpouseMarriageYear),
    });
    setIsSubmitting(false);
    if (result.ok) {
      setNewSpouseName('');
      setNewSpouseMarriageYear('');
    } else {
      setActionError(result.error ?? 'Không thể thêm. Vui lòng thử lại.');
    }
  }

  const lifespan = lifespanOf(birthYear, deathYear);

  return (
    <aside className="fixed inset-y-0 right-0 z-40 w-80 overflow-y-auto border-default border-l bg-surface p-4 shadow-lg">
      <button type="button" onClick={onClose} className="mb-4 text-sm text-muted hover:text-default">
        Đóng ✕
      </button>

      {isEditing ? (
        <div className="space-y-3">
          <div>
            <label className="text-xs text-muted">Họ tên</label>
            <input
              value={editedName}
              onChange={(e) => setEditedName(e.target.value)}
              className="mt-1 w-full rounded-lg border-default border bg-app px-2 py-1 text-sm text-default focus:outline-none"
            />
          </div>
          <div className="flex gap-x-2">
            <div className="flex-1">
              <label className="text-xs text-muted">Năm sinh</label>
              <input
                type="number"
                value={editedBirthYear}
                onChange={(e) => setEditedBirthYear(e.target.value)}
                className="mt-1 w-full rounded-lg border-default border bg-app px-2 py-1 text-sm text-default focus:outline-none"
              />
            </div>
            <div className="flex-1">
              <label className="text-xs text-muted">Năm mất</label>
              <input
                type="number"
                value={editedDeathYear}
                onChange={(e) => setEditedDeathYear(e.target.value)}
                className="mt-1 w-full rounded-lg border-default border bg-app px-2 py-1 text-sm text-default focus:outline-none"
              />
            </div>
          </div>
          <div>
            <label className="text-xs text-muted">Giới tính</label>
            <select
              value={editedGender}
              onChange={(e) => setEditedGender(e.target.value)}
              className="mt-1 w-full rounded-lg border-default border bg-app px-2 py-1 text-sm text-default focus:outline-none"
            >
              <option value="">Không rõ</option>
              <option value="male">Nam</option>
              <option value="female">Nữ</option>
              <option value="other">Khác</option>
            </select>
          </div>
          <div>
            <label className="text-xs text-muted">Ghi chú</label>
            <textarea
              value={editedNotes}
              onChange={(e) => setEditedNotes(e.target.value)}
              rows={3}
              className="mt-1 w-full rounded-lg border-default border bg-app px-2 py-1 text-sm text-default focus:outline-none"
            />
          </div>
          <div className="flex items-center gap-x-2">
            <button type="button" onClick={handleSave} disabled={isSubmitting} className="whitespace-nowrap text-sm accent-text hover:underline disabled:opacity-50">
              Lưu
            </button>
            <button type="button" onClick={() => setIsEditing(false)} className="whitespace-nowrap text-sm text-muted hover:text-default">
              Huỷ
            </button>
          </div>
        </div>
      ) : (
        <div>
          <div className="flex items-center justify-between gap-x-2">
            <h2 className="text-lg font-semibold text-default">{name}</h2>
            <button type="button" onClick={startEditing} className="whitespace-nowrap text-sm text-muted hover:text-default">
              Sửa
            </button>
          </div>
          {lifespan && <p className="mt-1 text-sm text-muted">{lifespan}</p>}
          {gender && <p className="mt-1 text-sm text-muted">{GENDER_LABELS[gender]}</p>}
          {notes && <p className="mt-2 whitespace-pre-wrap text-sm text-default">{notes}</p>}
        </div>
      )}

      <p className="mt-1 text-sm text-muted">Đời thứ {generation}</p>

      {ancestors.length > 0 && <p className="mt-4 text-xs text-muted">{ancestors.join(' → ')}</p>}

      {actionError && <p className="mt-4 text-sm text-danger">{actionError}</p>}

      <div className="mt-6">
        <h3 className="text-sm font-medium text-default">Vợ/chồng ({spouses.length})</h3>
        {spouses.length > 0 && (
          <ul className="mt-2 space-y-3">
            {spouses.map((spouse) =>
              editingSpouseId === spouse.marriageId && spouseDraft ? (
                <li key={spouse.marriageId} className="space-y-2 rounded-lg border-default border p-2">
                  <input
                    value={spouseDraft.name}
                    onChange={(e) => setSpouseDraft({ ...spouseDraft, name: e.target.value })}
                    className="w-full rounded-lg border-default border bg-app px-2 py-1 text-sm text-default focus:outline-none"
                  />
                  <div className="flex gap-x-2">
                    <input
                      type="number"
                      value={spouseDraft.birthYear}
                      onChange={(e) => setSpouseDraft({ ...spouseDraft, birthYear: e.target.value })}
                      placeholder="Năm sinh"
                      className="w-full rounded-lg border-default border bg-app px-2 py-1 text-sm text-default placeholder:text-muted focus:outline-none"
                    />
                    <input
                      type="number"
                      value={spouseDraft.deathYear}
                      onChange={(e) => setSpouseDraft({ ...spouseDraft, deathYear: e.target.value })}
                      placeholder="Năm mất"
                      className="w-full rounded-lg border-default border bg-app px-2 py-1 text-sm text-default placeholder:text-muted focus:outline-none"
                    />
                  </div>
                  <select
                    value={spouseDraft.gender}
                    onChange={(e) => setSpouseDraft({ ...spouseDraft, gender: e.target.value })}
                    className="w-full rounded-lg border-default border bg-app px-2 py-1 text-sm text-default focus:outline-none"
                  >
                    <option value="">Không rõ</option>
                    <option value="male">Nam</option>
                    <option value="female">Nữ</option>
                    <option value="other">Khác</option>
                  </select>
                  <input
                    type="number"
                    value={spouseDraft.marriageYear}
                    onChange={(e) => setSpouseDraft({ ...spouseDraft, marriageYear: e.target.value })}
                    placeholder="Năm cưới"
                    className="w-full rounded-lg border-default border bg-app px-2 py-1 text-sm text-default placeholder:text-muted focus:outline-none"
                  />
                  <textarea
                    value={spouseDraft.notes}
                    onChange={(e) => setSpouseDraft({ ...spouseDraft, notes: e.target.value })}
                    rows={2}
                    placeholder="Ghi chú"
                    className="w-full rounded-lg border-default border bg-app px-2 py-1 text-sm text-default placeholder:text-muted focus:outline-none"
                  />
                  <div className="flex items-center gap-x-2">
                    <button type="button" onClick={() => handleSaveSpouse(spouse.marriageId)} disabled={isSubmitting} className="whitespace-nowrap text-sm accent-text hover:underline disabled:opacity-50">
                      Lưu
                    </button>
                    <button
                      type="button"
                      onClick={() => {
                        setEditingSpouseId(null);
                        setSpouseDraft(null);
                      }}
                      className="whitespace-nowrap text-sm text-muted hover:text-default"
                    >
                      Huỷ
                    </button>
                  </div>
                </li>
              ) : (
                <li key={spouse.marriageId} className="text-sm text-default">
                  <div className="flex items-center justify-between gap-x-2">
                    <span>{spouse.name}</span>
                    <div className="flex items-center gap-x-2">
                      <button type="button" onClick={() => startEditingSpouse(spouse)} className="whitespace-nowrap text-xs text-muted hover:text-default">
                        Sửa
                      </button>
                      <button type="button" onClick={() => handleDeleteSpouse(spouse)} className="whitespace-nowrap text-xs text-danger hover:underline">
                        Xoá
                      </button>
                    </div>
                  </div>
                  {(lifespanOf(spouse.birthYear, spouse.deathYear) || spouse.marriageYear !== null) && (
                    <p className="text-xs text-muted">
                      {lifespanOf(spouse.birthYear, spouse.deathYear)}
                      {spouse.marriageYear !== null && ` · Cưới năm ${spouse.marriageYear}`}
                    </p>
                  )}
                </li>
              )
            )}
          </ul>
        )}
        <div className="mt-3 flex items-center gap-x-2">
          <input
            value={newSpouseName}
            onChange={(e) => setNewSpouseName(e.target.value)}
            placeholder="Tên vợ/chồng..."
            className="w-full rounded-lg border-default border bg-app px-2 py-1 text-sm text-default placeholder:text-muted focus:outline-none"
          />
          <input
            type="number"
            value={newSpouseMarriageYear}
            onChange={(e) => setNewSpouseMarriageYear(e.target.value)}
            placeholder="Năm cưới"
            className="w-24 shrink-0 rounded-lg border-default border bg-app px-2 py-1 text-sm text-default placeholder:text-muted focus:outline-none"
          />
          <button type="button" onClick={handleAddSpouse} disabled={isSubmitting || !newSpouseName.trim()} className="whitespace-nowrap text-sm accent-text hover:underline disabled:opacity-50">
            Thêm
          </button>
        </div>
      </div>

      <div className="mt-6">
        <h3 className="text-sm font-medium text-default">Con ({childMembers.length})</h3>
        {childMembers.length > 0 && (
          <ul className="mt-2 space-y-1">
            {childMembers.map((child) => (
              <li key={child.name}>
                <button type="button" onClick={child.onSelect} className="text-sm text-default hover:accent-text">
                  {child.name}
                </button>
              </li>
            ))}
          </ul>
        )}
        <div className="mt-3 flex items-center gap-x-2">
          <input value={newChildName} onChange={(e) => setNewChildName(e.target.value)} placeholder="Tên con mới..." className="w-full rounded-lg border-default border bg-app px-2 py-1 text-sm text-default placeholder:text-muted focus:outline-none" />
          <button type="button" onClick={handleAddChild} disabled={isSubmitting || !newChildName.trim()} className="whitespace-nowrap text-sm accent-text hover:underline disabled:opacity-50">
            Thêm con
          </button>
        </div>
      </div>

      <button type="button" onClick={handleDelete} disabled={isSubmitting} className="mt-6 text-sm text-danger hover:underline disabled:opacity-50">
        Xoá thành viên
      </button>
    </aside>
  );
}
```

- [ ] **Step 2: Verify no regressions**

Run: `npx tsc --noEmit`
Expected: FAILS at this point — `genealogy-tree/page.tsx` (Task 7) still passes the old `MemberDetailPanelProps` shape (missing `spouses`/`onAddSpouse`/`onUpdateSpouse`/`onDeleteSpouse`). This is expected; Task 7 fixes it. Confirm the errors are only in `src/app/genealogy-tree/page.tsx` and only about the new props, not about `MemberDetailPanel.tsx` itself.

- [ ] **Step 3: Commit**

```bash
git add src/components/tree/MemberDetailPanel.tsx
git commit -m "feat: add spouse list, edit, and add form to MemberDetailPanel"
```

---

### Task 7: Wire spouses into `genealogy-tree/page.tsx`

**Files:**
- Modify: `genealogy-web/src/app/genealogy-tree/page.tsx`

**Interfaces:**
- Consumes: `Spouse` (Task 5), `PanelSpouse`/`SpouseAddInput`/`SpouseUpdateInput` (Task 6).

- [ ] **Step 1: Update imports and types**

In `genealogy-web/src/app/genealogy-tree/page.tsx`, replace:

```ts
import { MemberDetailPanel, type MemberUpdateInput, type MutationResult } from '@/components/tree/MemberDetailPanel';
import { TreeControls } from '@/components/tree/TreeControls';
import { getMemberAtPath } from '@/lib/tree/search';
import type { FamilyMember, Gender } from '@/lib/tree/types';
```

with:

```ts
import {
  MemberDetailPanel,
  type MemberUpdateInput,
  type MutationResult,
  type PanelSpouse,
  type SpouseAddInput,
  type SpouseUpdateInput,
} from '@/components/tree/MemberDetailPanel';
import { TreeControls } from '@/components/tree/TreeControls';
import { getMemberAtPath } from '@/lib/tree/search';
import type { FamilyMember, Gender, Spouse } from '@/lib/tree/types';
```

Replace:

```ts
type SelectedMember = {
  id: number;
  parentId: number | null;
  name: string;
  generation: number;
  ancestorPath: string[];
  childrenNames: string[];
  birthYear: number | null;
  deathYear: number | null;
  gender: Gender | null;
  notes: string | null;
};

// The API's tree nodes carry fields that react-d3-tree's own RawNodeDatum/TreeNodeDatum
// types don't declare (they only know about `name`/`children`/`attributes`) - these
// survive at runtime since react-d3-tree doesn't strip unknown properties.
type MemberNodeData = TreeNodeDatum & {
  id: number;
  birth_year?: number | null;
  death_year?: number | null;
  gender?: Gender | null;
  notes?: string | null;
};
```

with:

```ts
type SelectedMember = {
  id: number;
  parentId: number | null;
  name: string;
  generation: number;
  ancestorPath: string[];
  childrenNames: string[];
  birthYear: number | null;
  deathYear: number | null;
  gender: Gender | null;
  notes: string | null;
  spouses: PanelSpouse[];
};

// The API's tree nodes carry fields that react-d3-tree's own RawNodeDatum/TreeNodeDatum
// types don't declare (they only know about `name`/`children`/`attributes`) - these
// survive at runtime since react-d3-tree doesn't strip unknown properties.
type MemberNodeData = TreeNodeDatum & {
  id: number;
  birth_year?: number | null;
  death_year?: number | null;
  gender?: Gender | null;
  notes?: string | null;
  spouses?: Spouse[];
};

function toPanelSpouses(spouses: Spouse[] | undefined): PanelSpouse[] {
  return (spouses ?? []).map((spouse) => ({
    marriageId: spouse.marriage_id,
    spouseId: spouse.id,
    name: spouse.full_name,
    birthYear: spouse.birth_year,
    deathYear: spouse.death_year,
    gender: spouse.gender,
    notes: spouse.notes,
    marriageYear: spouse.marriage_year,
  }));
}
```

- [ ] **Step 2: Populate `spouses` in `handleNodeClick` and `handleSelectChild`**

Replace:

```ts
    const childrenNames = data.children?.map((child) => child.name) ?? [];
    setSelectedMember({
      id: data.id,
      parentId: parentData ? parentData.id : null,
      name: data.name,
      generation: ancestorPath.length,
      ancestorPath,
      childrenNames,
      birthYear: data.birth_year ?? null,
      deathYear: data.death_year ?? null,
      gender: data.gender ?? null,
      notes: data.notes ?? null,
    });
  }

  function handleSelectChild(childName: string) {
    if (!selectedMember) return;
    const newPath = [...selectedMember.ancestorPath, childName];
    const member = getMemberAtPath(familyTree, newPath);
    if (!member || member.id === undefined) return;
    setSelectedMember({
      id: member.id,
      parentId: selectedMember.id,
      name: member.name,
      generation: newPath.length,
      ancestorPath: newPath,
      childrenNames: member.children?.map((child) => child.name) ?? [],
      birthYear: member.birth_year ?? null,
      deathYear: member.death_year ?? null,
      gender: member.gender ?? null,
      notes: member.notes ?? null,
    });
  }
```

with:

```ts
    const childrenNames = data.children?.map((child) => child.name) ?? [];
    setSelectedMember({
      id: data.id,
      parentId: parentData ? parentData.id : null,
      name: data.name,
      generation: ancestorPath.length,
      ancestorPath,
      childrenNames,
      birthYear: data.birth_year ?? null,
      deathYear: data.death_year ?? null,
      gender: data.gender ?? null,
      notes: data.notes ?? null,
      spouses: toPanelSpouses(data.spouses),
    });
  }

  function handleSelectChild(childName: string) {
    if (!selectedMember) return;
    const newPath = [...selectedMember.ancestorPath, childName];
    const member = getMemberAtPath(familyTree, newPath);
    if (!member || member.id === undefined) return;
    setSelectedMember({
      id: member.id,
      parentId: selectedMember.id,
      name: member.name,
      generation: newPath.length,
      ancestorPath: newPath,
      childrenNames: member.children?.map((child) => child.name) ?? [],
      birthYear: member.birth_year ?? null,
      deathYear: member.death_year ?? null,
      gender: member.gender ?? null,
      notes: member.notes ?? null,
      spouses: toPanelSpouses(member.spouses),
    });
  }
```

- [ ] **Step 3: Add the three spouse mutation handlers**

Insert these three functions right after `handleDeleteMember` (before `renderNode`):

```ts
  async function handleAddSpouse(input: SpouseAddInput): Promise<MutationResult> {
    if (!selectedMember) return { ok: false, error: 'Không tìm thấy thành viên.' };
    try {
      const response = await fetch(`/api/members/${selectedMember.id}/marriages`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ spouse_full_name: input.name, marriage_year: input.marriageYear }),
      });
      if (!response.ok) return { ok: false, error: 'Không thể thêm. Vui lòng thử lại.' };
      const body: Spouse = await response.json();
      setSelectedMember({
        ...selectedMember,
        spouses: [...selectedMember.spouses, ...toPanelSpouses([body])],
      });
      onDataChanged();
      return { ok: true };
    } catch {
      return { ok: false, error: 'Không thể kết nối tới máy chủ.' };
    }
  }

  async function handleUpdateSpouse(
    marriageId: number,
    input: SpouseUpdateInput
  ): Promise<MutationResult> {
    if (!selectedMember) return { ok: false, error: 'Không tìm thấy thành viên.' };
    try {
      const response = await fetch(`/api/members/marriages/${marriageId}`, {
        method: 'PUT',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          spouse_full_name: input.name,
          spouse_birth_year: input.birthYear,
          spouse_death_year: input.deathYear,
          spouse_gender: input.gender,
          spouse_notes: input.notes,
          marriage_year: input.marriageYear,
        }),
      });
      if (!response.ok) return { ok: false, error: 'Không thể lưu. Vui lòng thử lại.' };
      setSelectedMember({
        ...selectedMember,
        spouses: selectedMember.spouses.map((spouse) =>
          spouse.marriageId === marriageId
            ? {
                ...spouse,
                name: input.name,
                birthYear: input.birthYear,
                deathYear: input.deathYear,
                gender: input.gender,
                notes: input.notes,
                marriageYear: input.marriageYear,
              }
            : spouse
        ),
      });
      onDataChanged();
      return { ok: true };
    } catch {
      return { ok: false, error: 'Không thể kết nối tới máy chủ.' };
    }
  }

  async function handleDeleteSpouse(spouseId: number): Promise<MutationResult> {
    if (!selectedMember) return { ok: false, error: 'Không tìm thấy thành viên.' };
    try {
      const response = await fetch(`/api/members/${spouseId}`, {
        method: 'DELETE',
        credentials: 'include',
      });
      if (!response.ok) return { ok: false, error: 'Không thể xoá. Vui lòng thử lại.' };
      setSelectedMember({
        ...selectedMember,
        spouses: selectedMember.spouses.filter((spouse) => spouse.spouseId !== spouseId),
      });
      onDataChanged();
      return { ok: true };
    } catch {
      return { ok: false, error: 'Không thể kết nối tới máy chủ.' };
    }
  }
```

- [ ] **Step 4: Wire the new props into `<MemberDetailPanel>`**

Replace:

```tsx
        <MemberDetailPanel
          name={selectedMember.name}
          generation={selectedMember.generation}
          ancestorPath={selectedMember.ancestorPath}
          birthYear={selectedMember.birthYear}
          deathYear={selectedMember.deathYear}
          gender={selectedMember.gender}
          notes={selectedMember.notes}
          childMembers={selectedMember.childrenNames.map((childName) => ({
            name: childName,
            onSelect: () => handleSelectChild(childName),
          }))}
          onClose={() => setSelectedMember(null)}
          onUpdate={handleUpdateMember}
          onAddChild={handleAddChildMember}
          onDelete={handleDeleteMember}
        />
```

with:

```tsx
        <MemberDetailPanel
          name={selectedMember.name}
          generation={selectedMember.generation}
          ancestorPath={selectedMember.ancestorPath}
          birthYear={selectedMember.birthYear}
          deathYear={selectedMember.deathYear}
          gender={selectedMember.gender}
          notes={selectedMember.notes}
          spouses={selectedMember.spouses}
          childMembers={selectedMember.childrenNames.map((childName) => ({
            name: childName,
            onSelect: () => handleSelectChild(childName),
          }))}
          onClose={() => setSelectedMember(null)}
          onUpdate={handleUpdateMember}
          onAddChild={handleAddChildMember}
          onDelete={handleDeleteMember}
          onAddSpouse={handleAddSpouse}
          onUpdateSpouse={handleUpdateSpouse}
          onDeleteSpouse={handleDeleteSpouse}
        />
```

- [ ] **Step 5: Verify**

Run: `npx tsc --noEmit`
Expected: no errors.

Run: `npm run lint`
Expected: no errors.

Run: `npx vitest run`
Expected: PASS (14 tests).

- [ ] **Step 6: Commit**

```bash
git add src/app/genealogy-tree/page.tsx
git commit -m "feat: wire spouse add/edit/delete into the tree page"
```

---

### Task 8: End-to-end verification and docs refresh

**Files:**
- No new source files. Verification only, plus `CLAUDE.md` refresh in both repos.

- [ ] **Step 1: Full backend test suite**

Run (from `genealogy-api/`): `uv run pytest`
Expected: all tests pass (existing + new marriage tests).

- [ ] **Step 2: Full frontend checks and production build**

Run (from `genealogy-web/`, with no dev server running against the same `.next` directory — kill any listener on port 3000 first): `npx tsc --noEmit && npm run lint && npx vitest run && npm run build`
Expected: all pass; build succeeds.

- [ ] **Step 3: Start both servers**

Start `genealogy-api` (`uv run uvicorn app.main:app --reload --port 8000`) and `genealogy-web` (`npm run dev`) as background processes.

- [ ] **Step 4: Browser verification with Playwright**

Write a script (in the session's scratch/temp directory, not committed to either repo) that:
1. Registers a fresh test user via `/signup`, logs in via `/login`.
2. Opens the tree, clicks a member node.
3. Adds a spouse via the "Thêm" form (name + marriage year) and confirms the new row appears with the correct name and "Cưới năm ..." text.
4. Clicks "Sửa" on that spouse row, fills birth year, death year, gender, notes, saves, and confirms the row now shows the lifespan and gender.
5. Clicks "Xoá" on the spouse row, confirms the browser `confirm()` dialog, and confirms the row disappears from the panel.
6. Reloads the page and re-opens the same member to confirm the spouse list matches what remains (i.e. the backend state agrees with the UI after the delete).

Run it against the two running servers and confirm every step passes.

- [ ] **Step 5: Clean up test data**

Any member/spouse rows created directly against the shared tree during Step 4 that weren't already deleted by the test itself must be removed via the running API (`DELETE /members/{id}`) so the shared tree isn't left with leftover test data. Do not use `psql -c` for any cleanup involving non-ASCII text — use the API directly (per the project's standing UTF-8/shell-encoding note).

- [ ] **Step 6: Stop both servers**

Kill the port 3000 and port 8000 listeners.

- [ ] **Step 7: Refresh `CLAUDE.md` in both repos**

In `genealogy-api/CLAUDE.md`, add a short paragraph under the `Member` section describing the `marriages` table, the root-exclusion rule in `_build_tree`, and the `POST /{member_id}/marriages` / `PUT /marriages/{marriage_id}` endpoints (mention that deleting a spouse reuses `DELETE /members/{id}` via `ON DELETE CASCADE`).

In `genealogy-web/CLAUDE.md`, add a short paragraph under the member-details section describing the spouses UI in `MemberDetailPanel` and the three new handlers in `genealogy-tree/page.tsx`.

Commit each repo's `CLAUDE.md` change separately:

```bash
# in genealogy-api/
git add CLAUDE.md
git commit -m "docs: document the marriage feature"
```

```bash
# in genealogy-web/
git add CLAUDE.md
git commit -m "docs: document the spouse UI"
```
