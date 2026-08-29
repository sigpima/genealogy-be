# Member Avatar Photo Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a top-level tree member have an optional avatar photo, shown as a small circular thumbnail on the tree node and a larger image in the detail panel, uploaded/replaced/removed from the existing "Sửa" form.

**Architecture:** `Member` gains a nullable `avatar_url` column. Files are saved to local disk under a configurable `UPLOAD_DIR` (default `uploads/avatars/`), served via FastAPI `StaticFiles` mounted at `/uploads`, proxied by Next.js the same way `/api/*` already is. Two new endpoints, `POST /members/{id}/avatar` (multipart upload) and `DELETE /members/{id}/avatar`, live in the existing member router. The frontend's single "Lưu" button internally issues the avatar upload/delete call first (if the user changed the photo), then the existing JSON `PUT` for the other fields — the general member-update JSON contract is untouched.

**Tech Stack:** FastAPI, SQLAlchemy 2.0 async, Pydantic v2, Alembic, `python-multipart` (backend, `genealogy-api/`); Next.js 15, React 19, TypeScript (frontend, `genealogy-web/`).

**Spec:** `docs/superpowers/specs/2026-08-29-avatar-design.md`

## Global Constraints

- Avatars apply only to top-level tree members — `SpouseInfo` does not gain an `avatar_url` field or any upload UI in this iteration.
- Allowed content types: `image/jpeg`, `image/png`, `image/webp`. Max size: 5 MB. Both checked server-side; reject with `400`.
- `avatar_url` is always a path starting with `/uploads/...`, never an absolute URL with a host — the frontend proxies it, the same way it already proxies `/api/*`.
- No image resizing/cropping in this iteration — stored as uploaded.
- Every test in this repo that spins up the `client` fixture must get an isolated, per-test `UPLOAD_DIR` (a pytest `tmp_path`) so test runs never write into the repo's real `uploads/` folder — this applies to the shared `tests/conftest.py` fixture, not just avatar-specific tests.
- Both repos are plain `main`-branch checkouts with no remote configured — commit directly to `main` in each repo per task.

---

### Task 1: `python-multipart` dependency, `Member.avatar_url` column, and migration

**Files:**
- Modify: `genealogy-api/pyproject.toml` (via `uv add`)
- Modify: `genealogy-api/app/models/member.py`
- Modify: `genealogy-api/tests/test_member_model.py`

**Interfaces:**
- Produces: `Member.avatar_url: str | None` — consumed by Task 3 (schemas), Task 4 (endpoints).

- [ ] **Step 1: Install the multipart dependency**

Run (from `genealogy-api/`): `uv add python-multipart`
Expected: `pyproject.toml` and the lock file gain the dependency; command exits 0.

- [ ] **Step 2: Write the failing test**

Append to `genealogy-api/tests/test_member_model.py`:

```python
async def test_create_member_without_avatar_defaults_to_none(session):
    from app.models.member import Member

    member = Member(full_name="No Avatar")
    session.add(member)
    await session.commit()
    await session.refresh(member)

    assert member.avatar_url is None
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `uv run pytest tests/test_member_model.py -v`
Expected: FAIL — `AttributeError: 'Member' object has no attribute 'avatar_url'`

- [ ] **Step 4: Add the column**

In `genealogy-api/app/models/member.py`, change:

```python
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
```

to:

```python
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `uv run pytest tests/test_member_model.py -v`
Expected: PASS (5 tests)

- [ ] **Step 6: Generate and apply the Alembic migration**

Requires the local Postgres service running, `DATABASE_URL` pointed at it, already at head (see `genealogy-api/CLAUDE.md`).

Run: `uv run alembic revision --autogenerate -m "add member avatar_url"`

Open the generated file under `genealogy-api/alembic/versions/` and confirm `upgrade()` contains:
```python
op.add_column('members', sa.Column('avatar_url', sa.String(length=512), nullable=True))
```

Run: `uv run alembic upgrade head`
Expected: applies with no errors.

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml uv.lock app/models/member.py alembic/versions/ tests/test_member_model.py
git commit -m "feat: add Member.avatar_url column and migration"
```

---

### Task 2: `UPLOAD_DIR` setting, per-test isolation, and static file mount

**Files:**
- Modify: `genealogy-api/app/core/config.py`
- Modify: `genealogy-api/app/main.py`
- Modify: `genealogy-api/tests/conftest.py`
- Modify: `genealogy-api/.gitignore`
- Test: `genealogy-api/tests/test_config.py`

**Interfaces:**
- Produces: `Settings.upload_dir: str`, an `upload_dir` pytest fixture (in `conftest.py`) — consumed by Task 4's tests.

- [ ] **Step 1: Write the failing test**

Append to `genealogy-api/tests/test_config.py`:

```python
def test_settings_upload_dir_defaults_to_uploads(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@localhost/db")
    monkeypatch.setenv("JWT_SECRET", "test-secret")
    monkeypatch.delenv("UPLOAD_DIR", raising=False)

    settings = Settings(_env_file=None)

    assert settings.upload_dir == "uploads"


def test_settings_reads_upload_dir_from_env(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@localhost/db")
    monkeypatch.setenv("JWT_SECRET", "test-secret")
    monkeypatch.setenv("UPLOAD_DIR", "/tmp/custom-uploads")

    settings = Settings(_env_file=None)

    assert settings.upload_dir == "/tmp/custom-uploads"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_config.py -v`
Expected: FAIL — `AttributeError: 'Settings' object has no attribute 'upload_dir'`

- [ ] **Step 3: Add the setting**

In `genealogy-api/app/core/config.py`, change:

```python
    frontend_origin: str = "http://localhost:3000"
    cookie_secure: bool = False
```

to:

```python
    frontend_origin: str = "http://localhost:3000"
    cookie_secure: bool = False
    upload_dir: str = "uploads"
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_config.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Mount static files and ensure the directory exists**

In `genealogy-api/app/main.py`, change:

```python
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.config import get_settings
from app.routers.auth import router as auth_router
from app.routers.member import router as member_router

settings = get_settings()

app = FastAPI(title="genealogy-api")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(member_router)
```

to:

```python
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.core.config import get_settings
from app.routers.auth import router as auth_router
from app.routers.member import router as member_router

settings = get_settings()

Path(settings.upload_dir, "avatars").mkdir(parents=True, exist_ok=True)

app = FastAPI(title="genealogy-api")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/uploads", StaticFiles(directory=settings.upload_dir), name="uploads")

app.include_router(auth_router)
app.include_router(member_router)
```

This must happen before Task 4 adds any endpoint that touches `settings.upload_dir` — without it, `StaticFiles` raises `RuntimeError: Directory 'uploads' does not exist` the moment `app.main` is imported (i.e. every single test in the suite, since the `client` fixture imports it).

- [ ] **Step 6: Isolate `UPLOAD_DIR` per test**

In `genealogy-api/tests/conftest.py`, change:

```python
@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
    monkeypatch.setenv("JWT_SECRET", "test-secret")
    monkeypatch.setenv("JWT_EXPIRE_MINUTES", "60")
    from app.core.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
```

to:

```python
@pytest.fixture(autouse=True)
def _env(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
    monkeypatch.setenv("JWT_SECRET", "test-secret")
    monkeypatch.setenv("JWT_EXPIRE_MINUTES", "60")
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path))
    from app.core.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
```

Then add a new fixture right after `_env` (same file), so avatar tests can assert filesystem state without duplicating the temp directory:

```python
@pytest.fixture
def upload_dir(tmp_path) -> Path:
    return tmp_path
```

This needs `from pathlib import Path` added to the file's imports. Because pytest caches `tmp_path` per test, `_env` and `upload_dir` resolve to the *same* directory within one test.

- [ ] **Step 7: Add `uploads/` to `.gitignore`**

In `genealogy-api/.gitignore`, add a new line: `uploads/`

- [ ] **Step 8: Run the full suite**

Run: `uv run pytest`
Expected: all existing tests still pass (68 before this task) — this confirms the static mount doesn't break app startup and the new autouse fixture doesn't break any existing test.

- [ ] **Step 9: Commit**

```bash
git add app/core/config.py app/main.py tests/conftest.py tests/test_config.py .gitignore
git commit -m "feat: add UPLOAD_DIR setting, static file mount, and per-test isolation"
```

---

### Task 3: `avatar_url` on `MemberRead` / `MemberTreeNode`

**Files:**
- Modify: `genealogy-api/app/schemas/member.py`
- Modify: `genealogy-api/app/routers/member.py`
- Modify: `genealogy-api/tests/test_member_schemas.py`

**Interfaces:**
- Produces: `MemberRead.avatar_url`, `MemberTreeNode.avatar_url` — consumed by Task 4 (endpoints return `MemberRead`-shaped bodies for the general CRUD routes, which already pick up the new column automatically) and by `_build_tree`.

- [ ] **Step 1: Write the failing tests**

In `genealogy-api/tests/test_member_schemas.py`, update the `FakeMember` stub inside `test_member_read_from_attributes`:

```python
def test_member_read_from_attributes():
    from app.schemas.member import MemberRead

    class FakeMember:
        id = 1
        full_name = "A B"
        parent_id = None
        birth_year = None
        death_year = None
        gender = None
        notes = None
        avatar_url = None
        created_at = datetime.now(timezone.utc)

    read = MemberRead.model_validate(FakeMember())
    assert read.id == 1
    assert read.full_name == "A B"
```

Then append two new tests at the end of the file:

```python
def test_member_read_accepts_avatar_url():
    from app.schemas.member import MemberRead

    class FakeMember:
        id = 1
        full_name = "A B"
        parent_id = None
        birth_year = None
        death_year = None
        gender = None
        notes = None
        avatar_url = "/uploads/avatars/x.jpg"
        created_at = datetime.now(timezone.utc)

    read = MemberRead.model_validate(FakeMember())
    assert read.avatar_url == "/uploads/avatars/x.jpg"


def test_member_tree_node_accepts_avatar_url():
    from app.schemas.member import MemberTreeNode

    node = MemberTreeNode(id=1, name="Root", avatar_url="/uploads/avatars/x.jpg")
    assert node.avatar_url == "/uploads/avatars/x.jpg"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_member_schemas.py -v`
Expected: FAIL — the updated `test_member_read_from_attributes` fails with a `ValidationError` (`avatar_url` field required), and the two new tests fail similarly / with `TypeError` for the unexpected `avatar_url` kwarg.

- [ ] **Step 3: Add the field to both schemas**

In `genealogy-api/app/schemas/member.py`, change `MemberRead`:

```python
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
```

to:

```python
class MemberRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    full_name: str
    parent_id: int | None
    birth_year: int | None
    death_year: int | None
    gender: Gender | None
    notes: str | None
    avatar_url: str | None
    created_at: datetime
```

And change `MemberTreeNode`:

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

to:

```python
class MemberTreeNode(BaseModel):
    id: int
    name: str
    birth_year: int | None = None
    death_year: int | None = None
    gender: Gender | None = None
    notes: str | None = None
    avatar_url: str | None = None
    spouses: list[SpouseInfo] = []
    children: list["MemberTreeNode"] = []
```

- [ ] **Step 4: Wire `_build_tree` to copy the field**

In `genealogy-api/app/routers/member.py`, inside `_build_tree`'s nested `build()` function, change:

```python
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
```

to:

```python
        return MemberTreeNode(
            id=node.id,
            name=node.full_name,
            birth_year=node.birth_year,
            death_year=node.death_year,
            gender=node.gender,
            notes=node.notes,
            avatar_url=node.avatar_url,
            spouses=spouses,
            children=[build(child) for child in children_by_parent.get(node.id, [])],
        )
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/test_member_schemas.py -v`
Expected: PASS (16 tests)

Run: `uv run pytest`
Expected: full suite passes (no regressions from the new required `MemberRead.avatar_url` field — `create_member`/`update_member` return ORM `Member` instances that always have the column, even if `None`).

- [ ] **Step 6: Commit**

```bash
git add app/schemas/member.py app/routers/member.py tests/test_member_schemas.py
git commit -m "feat: add avatar_url to MemberRead and MemberTreeNode"
```

---

### Task 4: Avatar upload and delete endpoints

**Files:**
- Modify: `genealogy-api/app/routers/member.py`
- Test: `genealogy-api/tests/test_avatar.py`

**Interfaces:**
- Consumes: `Settings.upload_dir`, `upload_dir` test fixture (Task 2).
- Produces: `POST /members/{id}/avatar`, `DELETE /members/{id}/avatar`.

- [ ] **Step 1: Write the failing tests**

Create `genealogy-api/tests/test_avatar.py`:

```python
async def _authenticate(client):
    await client.post(
        "/auth/register",
        json={
            "email": "avatar-tester@example.com",
            "password": "longenough",
            "full_name": "Tester",
        },
    )
    await client.post(
        "/auth/login",
        json={"email": "avatar-tester@example.com", "password": "longenough"},
    )


async def test_upload_avatar(client):
    await _authenticate(client)
    created = await client.post("/members", json={"full_name": "Root", "parent_id": None})
    member_id = created.json()["id"]

    response = await client.post(
        f"/members/{member_id}/avatar",
        files={"file": ("avatar.jpg", b"fake-image-bytes", "image/jpeg")},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["avatar_url"].startswith("/uploads/avatars/")
    assert body["avatar_url"].endswith(".jpg")


async def test_upload_avatar_writes_file_to_disk(client, upload_dir):
    await _authenticate(client)
    created = await client.post("/members", json={"full_name": "Root", "parent_id": None})
    member_id = created.json()["id"]

    response = await client.post(
        f"/members/{member_id}/avatar",
        files={"file": ("avatar.jpg", b"fake-image-bytes", "image/jpeg")},
    )
    relative_path = response.json()["avatar_url"].removeprefix("/uploads/")
    assert (upload_dir / relative_path).exists()


async def test_upload_avatar_replaces_previous_file(client, upload_dir):
    await _authenticate(client)
    created = await client.post("/members", json={"full_name": "Root", "parent_id": None})
    member_id = created.json()["id"]

    first = await client.post(
        f"/members/{member_id}/avatar",
        files={"file": ("first.png", b"first-bytes", "image/png")},
    )
    first_relative = first.json()["avatar_url"].removeprefix("/uploads/")
    first_path = upload_dir / first_relative
    assert first_path.exists()

    second = await client.post(
        f"/members/{member_id}/avatar",
        files={"file": ("second.png", b"second-bytes", "image/png")},
    )
    second_url = second.json()["avatar_url"]

    assert first.json()["avatar_url"] != second_url
    assert not first_path.exists()

    tree = await client.get("/members/tree")
    assert tree.json()["avatar_url"] == second_url


async def test_upload_avatar_rejects_disallowed_content_type(client):
    await _authenticate(client)
    created = await client.post("/members", json={"full_name": "Root", "parent_id": None})
    member_id = created.json()["id"]

    response = await client.post(
        f"/members/{member_id}/avatar",
        files={"file": ("avatar.gif", b"data", "image/gif")},
    )
    assert response.status_code == 400


async def test_upload_avatar_rejects_oversized_file(client):
    await _authenticate(client)
    created = await client.post("/members", json={"full_name": "Root", "parent_id": None})
    member_id = created.json()["id"]

    oversized = b"x" * (5 * 1024 * 1024 + 1)
    response = await client.post(
        f"/members/{member_id}/avatar",
        files={"file": ("avatar.jpg", oversized, "image/jpeg")},
    )
    assert response.status_code == 400


async def test_upload_avatar_rejects_nonexistent_member(client):
    await _authenticate(client)
    response = await client.post(
        "/members/9999/avatar",
        files={"file": ("avatar.jpg", b"data", "image/jpeg")},
    )
    assert response.status_code == 404


async def test_delete_avatar(client, upload_dir):
    await _authenticate(client)
    created = await client.post("/members", json={"full_name": "Root", "parent_id": None})
    member_id = created.json()["id"]
    upload = await client.post(
        f"/members/{member_id}/avatar",
        files={"file": ("avatar.jpg", b"data", "image/jpeg")},
    )
    relative_path = upload.json()["avatar_url"].removeprefix("/uploads/")
    file_path = upload_dir / relative_path
    assert file_path.exists()

    response = await client.delete(f"/members/{member_id}/avatar")
    assert response.status_code == 204
    assert not file_path.exists()

    tree = await client.get("/members/tree")
    assert tree.json()["avatar_url"] is None


async def test_delete_avatar_rejects_nonexistent_member(client):
    await _authenticate(client)
    response = await client.delete("/members/9999/avatar")
    assert response.status_code == 404


async def test_tree_includes_avatar_url(client):
    await _authenticate(client)
    created = await client.post("/members", json={"full_name": "Root", "parent_id": None})
    member_id = created.json()["id"]
    upload = await client.post(
        f"/members/{member_id}/avatar",
        files={"file": ("avatar.jpg", b"data", "image/jpeg")},
    )
    avatar_url = upload.json()["avatar_url"]

    tree = await client.get("/members/tree")
    assert tree.json()["avatar_url"] == avatar_url


async def test_avatar_endpoints_require_auth(client):
    response = await client.post(
        "/members/1/avatar", files={"file": ("avatar.jpg", b"data", "image/jpeg")}
    )
    assert response.status_code == 401

    response = await client.delete("/members/1/avatar")
    assert response.status_code == 401
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_avatar.py -v`
Expected: FAIL — `404 Not Found` for the new routes (they don't exist yet).

- [ ] **Step 3: Write the endpoints**

In `genealogy-api/app/routers/member.py`, change the import block from:

```python
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

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

to:

```python
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
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

ALLOWED_AVATAR_CONTENT_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}
MAX_AVATAR_SIZE = 5 * 1024 * 1024
```

Then add these two endpoints at the end of the file:

```python
@router.post("/{member_id}/avatar")
async def upload_avatar(
    member_id: int, file: UploadFile = File(...), db: AsyncSession = Depends(get_db)
) -> dict[str, str]:
    member = await db.get(Member, member_id)
    if member is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="member not found")

    extension = ALLOWED_AVATAR_CONTENT_TYPES.get(file.content_type or "")
    if extension is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="unsupported image type"
        )

    contents = await file.read()
    if len(contents) > MAX_AVATAR_SIZE:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="file too large")

    settings = get_settings()
    _delete_avatar_file(settings.upload_dir, member.avatar_url)

    avatars_dir = Path(settings.upload_dir) / "avatars"
    avatars_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{uuid.uuid4()}{extension}"
    (avatars_dir / filename).write_bytes(contents)

    avatar_url = f"/uploads/avatars/{filename}"
    member.avatar_url = avatar_url
    await db.commit()
    return {"avatar_url": avatar_url}


@router.delete("/{member_id}/avatar", status_code=status.HTTP_204_NO_CONTENT)
async def delete_avatar(member_id: int, db: AsyncSession = Depends(get_db)) -> None:
    member = await db.get(Member, member_id)
    if member is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="member not found")

    settings = get_settings()
    _delete_avatar_file(settings.upload_dir, member.avatar_url)
    member.avatar_url = None
    await db.commit()
```

And add this helper near the top of the file, right after the `ALLOWED_AVATAR_CONTENT_TYPES`/`MAX_AVATAR_SIZE` constants:

```python
def _delete_avatar_file(upload_dir: str, avatar_url: str | None) -> None:
    if not avatar_url:
        return
    relative_path = avatar_url.removeprefix("/uploads/")
    Path(upload_dir, relative_path).unlink(missing_ok=True)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_avatar.py -v`
Expected: PASS (10 tests)

Run: `uv run pytest`
Expected: full suite passes (no regressions).

- [ ] **Step 5: Commit**

```bash
git add app/routers/member.py tests/test_avatar.py
git commit -m "feat: add avatar upload and delete endpoints"
```

---

### Task 5: Frontend `avatar_url` type and static file proxy

**Files:**
- Modify: `genealogy-web/src/lib/tree/types.ts`
- Modify: `genealogy-web/next.config.ts`

**Interfaces:**
- Produces: `FamilyMember.avatar_url` — consumed by Task 6, 7, 8.

- [ ] **Step 1: Update the type file**

In `genealogy-web/src/lib/tree/types.ts`, change:

```ts
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

to:

```ts
export type FamilyMember = {
  id?: number;
  name: string;
  birth_year?: number | null;
  death_year?: number | null;
  gender?: Gender | null;
  notes?: string | null;
  avatar_url?: string | null;
  spouses?: Spouse[];
  children?: FamilyMember[];
};
```

- [ ] **Step 2: Add the static file proxy rule**

In `genealogy-web/next.config.ts`, change:

```ts
  async rewrites() {
    return [
      {
        source: '/api/:path*',
        destination: `${API_BASE_URL}/:path*`,
      },
    ];
  },
```

to:

```ts
  async rewrites() {
    return [
      {
        source: '/api/:path*',
        destination: `${API_BASE_URL}/:path*`,
      },
      {
        source: '/uploads/:path*',
        destination: `${API_BASE_URL}/uploads/:path*`,
      },
    ];
  },
```

- [ ] **Step 3: Verify no regressions**

Run: `npx vitest run`
Expected: PASS (14 tests).

Run: `npx tsc --noEmit`
Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add src/lib/tree/types.ts next.config.ts
git commit -m "feat: add avatar_url type and proxy uploaded files through Next.js"
```

---

### Task 6: Avatar thumbnail on the tree node

**Files:**
- Modify: `genealogy-web/src/app/genealogy-tree/page.tsx`

**Interfaces:**
- Consumes: `FamilyMember.avatar_url` (Task 5).

- [ ] **Step 1: Add `avatar_url` to `MemberNodeData`**

Change:

```ts
type MemberNodeData = TreeNodeDatum & {
  id: number;
  birth_year?: number | null;
  death_year?: number | null;
  gender?: Gender | null;
  notes?: string | null;
  spouses?: Spouse[];
};
```

to:

```ts
type MemberNodeData = TreeNodeDatum & {
  id: number;
  birth_year?: number | null;
  death_year?: number | null;
  gender?: Gender | null;
  notes?: string | null;
  avatar_url?: string | null;
  spouses?: Spouse[];
};
```

- [ ] **Step 2: Replace `renderNode`**

Replace the whole `renderNode` function:

```tsx
  function renderNode({ nodeDatum, hierarchyPointNode, toggleNode }: CustomNodeElementProps) {
    const hasChildren = Boolean(nodeDatum.children && nodeDatum.children.length > 0);
    const isCollapsed = nodeDatum.__rd3t.collapsed;
    const isHighlighted = nodeDatum.name === highlightedName;

    return (
      <g>
        <rect
          width={200}
          height={70}
          x={-100}
          y={-35}
          rx={14}
          ry={14}
          className="fill-surface stroke-border"
          style={{
            strokeWidth: isHighlighted ? 3 : 1.5,
            stroke: isHighlighted ? 'var(--color-accent)' : undefined,
          }}
          onClick={() => handleNodeClick(hierarchyPointNode)}
        />
        <text
          x={0}
          y={0}
          textAnchor="middle"
          dominantBaseline="middle"
          className="fill-text text-sm"
          onClick={() => handleNodeClick(hierarchyPointNode)}
        >
          {nodeDatum.name}
        </text>
        {hasChildren && (
          <g
            transform="translate(85, -25)"
            style={{ cursor: 'pointer' }}
            onClick={(event) => {
              event.stopPropagation();
              toggleNode();
            }}
          >
            <circle r={10} className="fill-primary" />
            <text
              textAnchor="middle"
              dominantBaseline="middle"
              className="fill-on-primary text-xs"
              style={{ pointerEvents: 'none' }}
            >
              {isCollapsed ? '+' : '−'}
            </text>
          </g>
        )}
      </g>
    );
  }
```

with:

```tsx
  function renderNode({ nodeDatum, hierarchyPointNode, toggleNode }: CustomNodeElementProps) {
    const hasChildren = Boolean(nodeDatum.children && nodeDatum.children.length > 0);
    const isCollapsed = nodeDatum.__rd3t.collapsed;
    const isHighlighted = nodeDatum.name === highlightedName;
    const data = nodeDatum as MemberNodeData;
    const avatarClipId = `avatar-clip-${data.id}`;

    return (
      <g>
        <rect
          width={200}
          height={70}
          x={-100}
          y={-35}
          rx={14}
          ry={14}
          className="fill-surface stroke-border"
          style={{
            strokeWidth: isHighlighted ? 3 : 1.5,
            stroke: isHighlighted ? 'var(--color-accent)' : undefined,
          }}
          onClick={() => handleNodeClick(hierarchyPointNode)}
        />
        {data.avatar_url ? (
          <>
            <clipPath id={avatarClipId}>
              <circle cx={0} cy={-12} r={14} />
            </clipPath>
            <image
              href={data.avatar_url}
              x={-14}
              y={-26}
              width={28}
              height={28}
              clipPath={`url(#${avatarClipId})`}
              preserveAspectRatio="xMidYMid slice"
              style={{ cursor: 'pointer' }}
              onClick={() => handleNodeClick(hierarchyPointNode)}
            />
          </>
        ) : (
          <>
            <circle
              cx={0}
              cy={-12}
              r={14}
              className="fill-primary"
              style={{ cursor: 'pointer' }}
              onClick={() => handleNodeClick(hierarchyPointNode)}
            />
            <text
              x={0}
              y={-12}
              textAnchor="middle"
              dominantBaseline="middle"
              className="fill-on-primary text-xs"
              style={{ pointerEvents: 'none' }}
            >
              {nodeDatum.name.charAt(0).toUpperCase()}
            </text>
          </>
        )}
        <text
          x={0}
          y={18}
          textAnchor="middle"
          dominantBaseline="middle"
          className="fill-text text-sm"
          onClick={() => handleNodeClick(hierarchyPointNode)}
        >
          {nodeDatum.name}
        </text>
        {hasChildren && (
          <g
            transform="translate(85, -25)"
            style={{ cursor: 'pointer' }}
            onClick={(event) => {
              event.stopPropagation();
              toggleNode();
            }}
          >
            <circle r={10} className="fill-primary" />
            <text
              textAnchor="middle"
              dominantBaseline="middle"
              className="fill-on-primary text-xs"
              style={{ pointerEvents: 'none' }}
            >
              {isCollapsed ? '+' : '−'}
            </text>
          </g>
        )}
      </g>
    );
  }
```

- [ ] **Step 3: Verify**

Run: `npx tsc --noEmit`
Expected: no errors (this task doesn't touch `MemberDetailPanel` props, so no cascading errors yet).

Run: `npm run lint`
Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add src/app/genealogy-tree/page.tsx
git commit -m "feat: render avatar thumbnail or initial-letter circle on tree nodes"
```

---

### Task 7: Avatar upload/preview/remove UI in `MemberDetailPanel`

**Files:**
- Modify: `genealogy-web/src/components/tree/MemberDetailPanel.tsx`

**Interfaces:**
- Produces: `AvatarUploadResult` type, new `MemberDetailPanelProps` fields `avatarUrl`, `onUploadAvatar`, `onDeleteAvatar` — consumed by Task 8.

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
export type AvatarUploadResult = { ok: boolean; error?: string; avatarUrl?: string };

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
  avatarUrl: string | null;
  childMembers: MemberDetailPanelChild[];
  spouses: PanelSpouse[];
  onClose: () => void;
  onUpdate: (input: MemberUpdateInput) => Promise<MutationResult>;
  onAddChild: (name: string) => Promise<MutationResult>;
  onDelete: () => Promise<MutationResult>;
  onAddSpouse: (input: SpouseAddInput) => Promise<MutationResult>;
  onUpdateSpouse: (marriageId: number, input: SpouseUpdateInput) => Promise<MutationResult>;
  onDeleteSpouse: (spouseId: number) => Promise<MutationResult>;
  onUploadAvatar: (file: File) => Promise<AvatarUploadResult>;
  onDeleteAvatar: () => Promise<MutationResult>;
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

function AvatarOrInitial({ src, initial, size }: { src: string | null; initial: string; size: number }) {
  if (src) {
    return (
      <img
        src={src}
        alt=""
        style={{ width: size, height: size }}
        className="rounded-full object-cover"
      />
    );
  }
  return (
    <div
      style={{ width: size, height: size }}
      className="flex items-center justify-center rounded-full bg-primary text-on-primary"
    >
      {initial.toUpperCase() || '?'}
    </div>
  );
}

export function MemberDetailPanel({
  name,
  generation,
  ancestorPath,
  birthYear,
  deathYear,
  gender,
  notes,
  avatarUrl,
  childMembers,
  spouses,
  onClose,
  onUpdate,
  onAddChild,
  onDelete,
  onAddSpouse,
  onUpdateSpouse,
  onDeleteSpouse,
  onUploadAvatar,
  onDeleteAvatar,
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

  const [avatarFile, setAvatarFile] = useState<File | null>(null);
  const [avatarPreviewUrl, setAvatarPreviewUrl] = useState<string | null>(null);
  const [removeAvatar, setRemoveAvatar] = useState(false);

  const [editingSpouseId, setEditingSpouseId] = useState<number | null>(null);
  const [spouseDraft, setSpouseDraft] = useState<SpouseDraft | null>(null);
  const [newSpouseName, setNewSpouseName] = useState('');
  const [newSpouseMarriageYear, setNewSpouseMarriageYear] = useState('');

  function resetAvatarDraft() {
    if (avatarPreviewUrl) URL.revokeObjectURL(avatarPreviewUrl);
    setAvatarFile(null);
    setAvatarPreviewUrl(null);
    setRemoveAvatar(false);
  }

  function startEditing() {
    setEditedName(name);
    setEditedBirthYear(toInputValue(birthYear));
    setEditedDeathYear(toInputValue(deathYear));
    setEditedGender(gender ?? '');
    setEditedNotes(notes ?? '');
    resetAvatarDraft();
    setIsEditing(true);
  }

  function handleAvatarFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0] ?? null;
    if (avatarPreviewUrl) URL.revokeObjectURL(avatarPreviewUrl);
    setAvatarFile(file);
    setRemoveAvatar(false);
    setAvatarPreviewUrl(file ? URL.createObjectURL(file) : null);
  }

  function handleRemoveAvatarClick() {
    if (avatarPreviewUrl) URL.revokeObjectURL(avatarPreviewUrl);
    setAvatarFile(null);
    setAvatarPreviewUrl(null);
    setRemoveAvatar(true);
  }

  async function handleSave() {
    if (!editedName.trim()) return;
    setIsSubmitting(true);
    setActionError(null);

    if (removeAvatar) {
      const avatarResult = await onDeleteAvatar();
      if (!avatarResult.ok) {
        setIsSubmitting(false);
        setActionError(avatarResult.error ?? 'Không thể xoá ảnh. Vui lòng thử lại.');
        return;
      }
    } else if (avatarFile) {
      const avatarResult = await onUploadAvatar(avatarFile);
      if (!avatarResult.ok) {
        setIsSubmitting(false);
        setActionError(avatarResult.error ?? 'Không thể tải ảnh lên. Vui lòng thử lại.');
        return;
      }
    }

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
      resetAvatarDraft();
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
  const editAvatarSrc = removeAvatar ? null : (avatarPreviewUrl ?? avatarUrl);
  const canRemoveAvatar = !removeAvatar && Boolean(avatarPreviewUrl || avatarUrl);

  return (
    <aside className="fixed inset-y-0 right-0 z-40 w-80 overflow-y-auto border-default border-l bg-surface p-4 shadow-lg">
      <button type="button" onClick={onClose} className="mb-4 text-sm text-muted hover:text-default">
        Đóng ✕
      </button>

      {isEditing ? (
        <div className="space-y-3">
          <div className="flex items-center gap-x-3">
            <AvatarOrInitial src={editAvatarSrc} initial={editedName.charAt(0)} size={64} />
            <div className="flex flex-col gap-y-1">
              <input type="file" accept="image/*" onChange={handleAvatarFileChange} className="text-xs text-muted" />
              {canRemoveAvatar && (
                <button
                  type="button"
                  onClick={handleRemoveAvatarClick}
                  className="whitespace-nowrap text-left text-xs text-danger hover:underline"
                >
                  Xoá ảnh
                </button>
              )}
            </div>
          </div>
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
            <button
              type="button"
              onClick={() => {
                resetAvatarDraft();
                setIsEditing(false);
              }}
              className="whitespace-nowrap text-sm text-muted hover:text-default"
            >
              Huỷ
            </button>
          </div>
        </div>
      ) : (
        <div>
          <div className="flex items-center gap-x-3">
            <AvatarOrInitial src={avatarUrl} initial={name.charAt(0)} size={64} />
            <div className="flex-1">
              <div className="flex items-center justify-between gap-x-2">
                <h2 className="text-lg font-semibold text-default">{name}</h2>
                <button type="button" onClick={startEditing} className="whitespace-nowrap text-sm text-muted hover:text-default">
                  Sửa
                </button>
              </div>
              {lifespan && <p className="mt-1 text-sm text-muted">{lifespan}</p>}
              {gender && <p className="mt-1 text-sm text-muted">{GENDER_LABELS[gender]}</p>}
            </div>
          </div>
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
Expected: FAILS at this point — `genealogy-tree/page.tsx` (Task 8) still passes the old `MemberDetailPanelProps` shape. Confirm the errors are only in `src/app/genealogy-tree/page.tsx` and only about the new props (`avatarUrl`, `onUploadAvatar`, `onDeleteAvatar` missing).

- [ ] **Step 3: Commit**

```bash
git add src/components/tree/MemberDetailPanel.tsx
git commit -m "feat: add avatar upload, preview, and remove UI to MemberDetailPanel"
```

---

### Task 8: Wire avatar upload/delete into `genealogy-tree/page.tsx`

**Files:**
- Modify: `genealogy-web/src/app/genealogy-tree/page.tsx`

**Interfaces:**
- Consumes: `AvatarUploadResult` (Task 7).

- [ ] **Step 1: Update imports**

Change:

```ts
import {
  MemberDetailPanel,
  type MemberUpdateInput,
  type MutationResult,
  type PanelSpouse,
  type SpouseAddInput,
  type SpouseUpdateInput,
} from '@/components/tree/MemberDetailPanel';
```

to:

```ts
import {
  MemberDetailPanel,
  type AvatarUploadResult,
  type MemberUpdateInput,
  type MutationResult,
  type PanelSpouse,
  type SpouseAddInput,
  type SpouseUpdateInput,
} from '@/components/tree/MemberDetailPanel';
```

- [ ] **Step 2: Add `avatarUrl` to `SelectedMember` and populate it**

Change:

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
```

to:

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
  avatarUrl: string | null;
  spouses: PanelSpouse[];
};
```

In `handleNodeClick`, change:

```ts
      birthYear: data.birth_year ?? null,
      deathYear: data.death_year ?? null,
      gender: data.gender ?? null,
      notes: data.notes ?? null,
      spouses: toPanelSpouses(data.spouses),
    });
  }
```

to:

```ts
      birthYear: data.birth_year ?? null,
      deathYear: data.death_year ?? null,
      gender: data.gender ?? null,
      notes: data.notes ?? null,
      avatarUrl: data.avatar_url ?? null,
      spouses: toPanelSpouses(data.spouses),
    });
  }
```

In `handleSelectChild`, change:

```ts
      birthYear: member.birth_year ?? null,
      deathYear: member.death_year ?? null,
      gender: member.gender ?? null,
      notes: member.notes ?? null,
      spouses: toPanelSpouses(member.spouses),
    });
  }
```

to:

```ts
      birthYear: member.birth_year ?? null,
      deathYear: member.death_year ?? null,
      gender: member.gender ?? null,
      notes: member.notes ?? null,
      avatarUrl: member.avatar_url ?? null,
      spouses: toPanelSpouses(member.spouses),
    });
  }
```

- [ ] **Step 3: Add the avatar upload/delete handlers**

Insert these two functions right after `handleDeleteSpouse` (before `renderNode`):

```ts
  async function handleUploadAvatar(file: File): Promise<AvatarUploadResult> {
    if (!selectedMember) return { ok: false, error: 'Không tìm thấy thành viên.' };
    try {
      const formData = new FormData();
      formData.append('file', file);
      const response = await fetch(`/api/members/${selectedMember.id}/avatar`, {
        method: 'POST',
        credentials: 'include',
        body: formData,
      });
      if (!response.ok) return { ok: false, error: 'Không thể tải ảnh lên. Vui lòng thử lại.' };
      const body: { avatar_url: string } = await response.json();
      setSelectedMember({ ...selectedMember, avatarUrl: body.avatar_url });
      onDataChanged();
      return { ok: true, avatarUrl: body.avatar_url };
    } catch {
      return { ok: false, error: 'Không thể kết nối tới máy chủ.' };
    }
  }

  async function handleDeleteAvatar(): Promise<MutationResult> {
    if (!selectedMember) return { ok: false, error: 'Không tìm thấy thành viên.' };
    try {
      const response = await fetch(`/api/members/${selectedMember.id}/avatar`, {
        method: 'DELETE',
        credentials: 'include',
      });
      if (!response.ok) return { ok: false, error: 'Không thể xoá ảnh. Vui lòng thử lại.' };
      setSelectedMember({ ...selectedMember, avatarUrl: null });
      onDataChanged();
      return { ok: true };
    } catch {
      return { ok: false, error: 'Không thể kết nối tới máy chủ.' };
    }
  }
```

- [ ] **Step 4: Wire the new props into `<MemberDetailPanel>`**

Change:

```tsx
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

to:

```tsx
          notes={selectedMember.notes}
          avatarUrl={selectedMember.avatarUrl}
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
          onUploadAvatar={handleUploadAvatar}
          onDeleteAvatar={handleDeleteAvatar}
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
git commit -m "feat: wire avatar upload and delete into the tree page"
```

---

### Task 9: End-to-end verification and docs refresh

**Files:**
- No new source files. Verification only, plus `CLAUDE.md` refresh in both repos.

- [ ] **Step 1: Full backend test suite**

Run (from `genealogy-api/`): `uv run pytest`
Expected: all tests pass.

- [ ] **Step 2: Full frontend checks and production build**

Run (from `genealogy-web/`, with no dev server running against the same `.next` directory): `npx tsc --noEmit && npm run lint && npx vitest run && npm run build`
Expected: all pass; build succeeds.

- [ ] **Step 3: Start both servers**

Start `genealogy-api` (`uv run uvicorn app.main:app --reload --port 8000`) and `genealogy-web` (`npm run dev`) as background processes.

- [ ] **Step 4: Browser verification with Playwright**

Write a script (in the session's scratch/temp directory) that:
1. Writes a small valid PNG file to disk (a 1x1 pixel PNG is enough — a fixed base64 literal decoded to bytes works, no image library needed).
2. Registers a fresh test user via `/signup`, logs in via `/login`.
3. Opens the tree, clicks the root member node, clicks "Sửa".
4. Uses `setInputFiles` on the file input to pick the PNG, confirms a preview appears (an `<img>` inside the edit form).
5. Clicks "Lưu" and confirms: the tree node now renders an `<image>` element (not just the initial-letter circle), and the panel's display mode shows an `<img>` with a `src` starting with `/uploads/avatars/`.
6. Re-opens edit mode, uploads a second PNG, saves, and confirms the `<img src>` changed to a different URL.
7. Re-opens edit mode, clicks "Xoá ảnh" without picking a new file, saves, and confirms both the panel and the tree node fall back to the initial-letter circle.
8. Reloads the page, re-selects the same member, and confirms the avatar-less state persisted (i.e. the backend's delete actually took effect, not just local UI state).

Run it against the two running servers and confirm every step passes.

- [ ] **Step 5: Clean up test data**

Delete any member created directly against the shared tree during Step 4 that wasn't already the pre-existing root, via `DELETE /members/{id}` through the running API. Do not use `psql -c` for any cleanup involving non-ASCII text.

- [ ] **Step 6: Stop both servers**

Kill the port 3000 and port 8000 listeners.

- [ ] **Step 7: Refresh `CLAUDE.md` in both repos**

In `genealogy-api/CLAUDE.md`, add a short paragraph describing `avatar_url`, the `UPLOAD_DIR` setting, the static mount, and the two avatar endpoints (mention the per-test isolation in `conftest.py`).

In `genealogy-web/CLAUDE.md`, add a short paragraph describing the avatar UI in `MemberDetailPanel` and tree node rendering, and the `/uploads` proxy rule.

Commit each repo's `CLAUDE.md` change separately:

```bash
# in genealogy-api/
git add CLAUDE.md
git commit -m "docs: document the avatar feature"
```

```bash
# in genealogy-web/
git add CLAUDE.md
git commit -m "docs: document the avatar UI"
```
