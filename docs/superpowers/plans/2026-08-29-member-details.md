# Member Details Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add optional `birth_year`, `death_year`, `gender`, `notes` to `Member`, returned by `GET /members/tree` and settable via `POST`/`PUT /members`.

**Architecture:** Four new nullable columns on the existing `members` table. `gender` is validated at the Pydantic layer via a `Gender(str, Enum)` (`male`/`female`/`other`), stored as a plain `String(10)`. A shared `death_year >= birth_year` check runs on both `MemberCreate` and `MemberUpdate`. All four fields are added to `MemberTreeNode` so the single existing tree fetch carries everything the frontend needs — no new endpoint.

**Tech Stack:** Same as the existing backend (FastAPI, SQLAlchemy async, Alembic, pytest/httpx).

**Spec:** `docs/superpowers/specs/2026-08-29-member-details-design.md`

## Global Constraints

- All four new fields are optional (`None` allowed) everywhere — real genealogy data is usually incomplete.
- `gender` is stored as a plain string column, not a native Postgres enum type — validated only at the Pydantic layer (`Gender(str, Enum)`).
- When assigning a `Gender` enum value to the `Member.gender` string column, always use `.value` explicitly (`payload.gender.value if payload.gender is not None else None`) rather than relying on the enum instance's own string coercion — `class X(str, Enum)` members can serialize as `"Gender.male"` instead of `"male"` depending on the code path, and DB drivers don't reliably normalize this.
- `death_year < birth_year` (when both given) is rejected with a Pydantic validator (→ FastAPI's automatic 422), not manual `HTTPException` logic in the router.

---

## File Structure

```
genealogy-api/
  app/
    models/member.py                                    # modified: + 4 columns
    schemas/member.py                                     # modified: + Gender enum, + 4 fields on 4 schemas
    routers/member.py                                       # modified: _build_tree, create_member, update_member pass the new fields
  alembic/versions/<rev>_add_member_details.py               # new (generated)
  tests/
    test_member_model.py                                      # modified: + detail-field tests
    test_member_schemas.py                                     # modified: + validation tests
    test_member.py                                              # modified: + router-level detail tests
```

---

### Task 1: Model fields

**Files:**
- Modify: `app/models/member.py`
- Test: `tests/test_member_model.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_member_model.py`:

```python
async def test_create_member_with_details(session):
    from app.models.member import Member

    member = Member(
        full_name="Detailed",
        birth_year=1950,
        death_year=2010,
        gender="male",
        notes="Some notes",
    )
    session.add(member)
    await session.commit()
    await session.refresh(member)

    assert member.birth_year == 1950
    assert member.death_year == 2010
    assert member.gender == "male"
    assert member.notes == "Some notes"


async def test_create_member_without_details_defaults_to_none(session):
    from app.models.member import Member

    member = Member(full_name="Minimal")
    session.add(member)
    await session.commit()
    await session.refresh(member)

    assert member.birth_year is None
    assert member.death_year is None
    assert member.gender is None
    assert member.notes is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_member_model.py -v`
Expected: FAIL with `TypeError: 'birth_year' is an invalid keyword argument for Member`

- [ ] **Step 3: Add the columns**

In `app/models/member.py`, update the import line and add the four columns:

```python
from sqlalchemy import DateTime, ForeignKey, String, Text, func
```

```python
    birth_year: Mapped[int | None] = mapped_column(nullable=True)
    death_year: Mapped[int | None] = mapped_column(nullable=True)
    gender: Mapped[str | None] = mapped_column(String(10), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
```

(placed after `parent_id`, before `created_at`)

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_member_model.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add app/models/member.py tests/test_member_model.py
git commit -m "feat: add birth_year/death_year/gender/notes to Member"
```

---

### Task 2: Schemas

**Files:**
- Modify: `app/schemas/member.py`
- Test: `tests/test_member_schemas.py`

**Interfaces:**
- Produces: `Gender(str, Enum)` with `male`/`female`/`other`; `MemberCreate`/`MemberUpdate`/`MemberRead`/`MemberTreeNode` all gain `birth_year: int | None`, `death_year: int | None`, `gender: Gender | None`, `notes: str | None`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_member_schemas.py`:

```python
def test_member_create_accepts_all_detail_fields():
    from app.schemas.member import Gender, MemberCreate

    data = MemberCreate(
        full_name="A B",
        parent_id=None,
        birth_year=1950,
        death_year=2010,
        gender=Gender.male,
        notes="hello",
    )
    assert data.birth_year == 1950
    assert data.gender == Gender.male


def test_member_create_rejects_death_before_birth():
    from app.schemas.member import MemberCreate

    with pytest.raises(ValidationError):
        MemberCreate(full_name="A B", birth_year=2010, death_year=1950)


def test_member_create_rejects_invalid_gender():
    from app.schemas.member import MemberCreate

    with pytest.raises(ValidationError):
        MemberCreate(full_name="A B", gender="unknown")


def test_member_update_rejects_death_before_birth():
    from app.schemas.member import MemberUpdate

    with pytest.raises(ValidationError):
        MemberUpdate(full_name="A B", birth_year=2010, death_year=1950)


def test_member_tree_node_accepts_detail_fields():
    from app.schemas.member import Gender, MemberTreeNode

    node = MemberTreeNode(
        id=1, name="Root", birth_year=1900, death_year=1980, gender=Gender.female, notes="n"
    )
    assert node.gender == Gender.female
    assert node.children == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_member_schemas.py -v`
Expected: FAIL — `ImportError: cannot import name 'Gender'`

- [ ] **Step 3: Write the implementation**

Replace `app/schemas/member.py`:

```python
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Gender(str, Enum):
    male = "male"
    female = "female"
    other = "other"


class MemberCreate(BaseModel):
    full_name: str = Field(min_length=1)
    parent_id: int | None = None
    birth_year: int | None = None
    death_year: int | None = None
    gender: Gender | None = None
    notes: str | None = None

    @model_validator(mode="after")
    def _check_years(self) -> "MemberCreate":
        if (
            self.birth_year is not None
            and self.death_year is not None
            and self.death_year < self.birth_year
        ):
            raise ValueError("death_year cannot be before birth_year")
        return self


class MemberUpdate(BaseModel):
    full_name: str = Field(min_length=1)
    parent_id: int | None = None
    birth_year: int | None = None
    death_year: int | None = None
    gender: Gender | None = None
    notes: str | None = None

    @model_validator(mode="after")
    def _check_years(self) -> "MemberUpdate":
        if (
            self.birth_year is not None
            and self.death_year is not None
            and self.death_year < self.birth_year
        ):
            raise ValueError("death_year cannot be before birth_year")
        return self


class MemberRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    full_name: str
    parent_id: int | None
    birth_year: int | None
    death_year: int | None
    gender: Gender | None
    notes: str | None
    created_at: datetime


class MemberTreeNode(BaseModel):
    id: int
    name: str
    birth_year: int | None = None
    death_year: int | None = None
    gender: Gender | None = None
    notes: str | None = None
    children: list["MemberTreeNode"] = []
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_member_schemas.py -v`
Expected: 9 passed

- [ ] **Step 5: Commit**

```bash
git add app/schemas/member.py tests/test_member_schemas.py
git commit -m "feat: add detail fields to Member schemas"
```

---

### Task 3: Router — pass details through create/update/tree

**Files:**
- Modify: `app/routers/member.py`
- Test: `tests/test_member.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_member.py`:

```python
async def test_create_and_fetch_member_with_details(client):
    await _authenticate(client)
    response = await client.post(
        "/members",
        json={
            "full_name": "Detailed",
            "parent_id": None,
            "birth_year": 1950,
            "death_year": 2010,
            "gender": "male",
            "notes": "Some notes",
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["birth_year"] == 1950
    assert body["gender"] == "male"

    tree_response = await client.get("/members/tree")
    tree = tree_response.json()
    assert tree["birth_year"] == 1950
    assert tree["death_year"] == 2010
    assert tree["gender"] == "male"
    assert tree["notes"] == "Some notes"


async def test_update_member_details(client):
    await _authenticate(client)
    created = await client.post("/members", json={"full_name": "Original", "parent_id": None})
    member_id = created.json()["id"]

    response = await client.put(
        f"/members/{member_id}",
        json={
            "full_name": "Original",
            "parent_id": None,
            "birth_year": 1900,
            "death_year": 1980,
            "gender": "female",
            "notes": "updated notes",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["birth_year"] == 1900
    assert body["gender"] == "female"
    assert body["notes"] == "updated notes"


async def test_create_rejects_death_before_birth(client):
    await _authenticate(client)
    response = await client.post(
        "/members",
        json={"full_name": "Bad Dates", "birth_year": 2010, "death_year": 1950},
    )
    assert response.status_code == 422
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_member.py -v`
Expected: FAIL — `test_create_and_fetch_member_with_details`/`test_update_member_details` fail their `assert body["birth_year"] == ...` (still `None`/absent, since the router doesn't set it yet); `test_create_rejects_death_before_birth` actually already passes at this point (Task 2's Pydantic validator already rejects it) — that's fine, it's here for completeness of router-level coverage.

- [ ] **Step 3: Update `_build_tree`, `create_member`, `update_member`**

In `app/routers/member.py`, update the inner `build` function inside `_build_tree`:

```python
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
```

Update `create_member`:

```python
    member = Member(
        full_name=payload.full_name,
        parent_id=payload.parent_id,
        birth_year=payload.birth_year,
        death_year=payload.death_year,
        gender=payload.gender.value if payload.gender is not None else None,
        notes=payload.notes,
    )
```

Update `update_member` (replace the two-line assignment block):

```python
    member.full_name = payload.full_name
    member.parent_id = payload.parent_id
    member.birth_year = payload.birth_year
    member.death_year = payload.death_year
    member.gender = payload.gender.value if payload.gender is not None else None
    member.notes = payload.notes
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_member.py -v`
Expected: 12 passed

- [ ] **Step 5: Run the full suite to confirm nothing broke**

Run: `uv run pytest -v`
Expected: all tests pass (42 existing + 2 + 5 + 3 = 52).

- [ ] **Step 6: Commit**

```bash
git add app/routers/member.py tests/test_member.py
git commit -m "feat: pass Member detail fields through create/update/tree"
```

---

### Task 4: Alembic migration

**Files:**
- Create: `alembic/versions/<rev>_add_member_details.py` (generated)

- [ ] **Step 1: Create a scratch Postgres database**

Run: `PGPASSWORD=postgres psql -U postgres -h localhost -p 5432 -c "DROP DATABASE IF EXISTS genealogy_api_migration_test;" -c "CREATE DATABASE genealogy_api_migration_test;"`

- [ ] **Step 2: Bring the scratch database up to the current head first**

Run: `DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/genealogy_api_migration_test JWT_SECRET=tmp uv run alembic upgrade head`
Expected: applies the existing `users` and `members` migrations.

- [ ] **Step 3: Generate the new migration**

Run: `DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/genealogy_api_migration_test JWT_SECRET=tmp uv run alembic revision --autogenerate -m "add member details"`
Expected: creates a migration containing `op.add_column('members', ...)` four times (`birth_year`, `death_year`, `gender`, `notes`), all nullable.

- [ ] **Step 4: Verify the migration applies cleanly**

Run: `DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/genealogy_api_migration_test JWT_SECRET=tmp uv run alembic upgrade head`
Expected: no errors.

- [ ] **Step 5: Verify the downgrade path works**

Run: `DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/genealogy_api_migration_test JWT_SECRET=tmp uv run alembic downgrade -1`
Expected: no errors, the four columns are dropped (confirm with `\d members` via `psql` if in doubt).

- [ ] **Step 6: Tear down the scratch database**

Run: `PGPASSWORD=postgres psql -U postgres -h localhost -p 5432 -c "DROP DATABASE IF EXISTS genealogy_api_migration_test;"`

- [ ] **Step 7: Apply the migration to the real local dev database**

Run: `uv run alembic upgrade head`
Expected: the four columns now exist on the real `genealogy` database's `members` table, all existing 691 rows getting `NULL` for them (safe — all nullable, no default needed).

- [ ] **Step 8: Commit**

```bash
git add alembic/versions
git commit -m "feat: add Alembic migration for Member detail fields"
```

---

### Task 5: Full verification + CLAUDE.md refresh

- [ ] **Step 1: Run the full test suite**

Run: `uv run pytest -v`
Expected: 52 passed.

- [ ] **Step 2: Refresh CLAUDE.md**

Invoke the `init` skill (Skill tool, `skill: "init"`) for this repository — it should document the new fields, the `Gender` enum's `.value` gotcha, and that `MemberTreeNode` now carries full detail data (not just name/children).

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: refresh CLAUDE.md for Member detail fields"
```

---

## Self-Review Notes

- **Spec coverage:** four new columns ✓ (Task 1), `Gender` enum + validation ✓ (Task 2), fields on all 4 schemas including `MemberTreeNode` ✓ (Task 2), router passes them through create/update/tree ✓ (Task 3), migration ✓ (Task 4), CLAUDE.md ✓ (Task 5). Non-goals (full dates, occupation field, frontend UI, lunar calendar) untouched.
- **Placeholder scan:** none — every step has literal code or an exact command with expected output.
- **Type consistency:** `Gender` used identically across `MemberCreate`/`MemberUpdate`/`MemberRead`/`MemberTreeNode`; `.value` extraction pattern applied consistently in both `create_member` and `update_member`; field names (`birth_year`, `death_year`, `gender`, `notes`) match exactly between the model, all four schemas, and the router.
