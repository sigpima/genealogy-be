# Member Tree Skeleton + Per-Member Detail Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Shrink `GET /members/tree` to `{id, name, children}` and add `GET /members/{id}` for everything else, so `genealogy-web` can fetch per-member detail lazily instead of the whole tree at once.

**Architecture:** `_build_tree` (unchanged) still builds the full-detail internal representation; a new `_to_skeleton` strips it down for `GET /members/tree`'s new `MemberSkeletonNode` response shape. A new `GET /members/{id}` builds a `MemberDetail` (birth/death/gender/notes/avatar/spouses) directly from the DB for one member, reusing the existing `_spouse_info` helper.

**Tech Stack:** Same as the existing backend (FastAPI, SQLAlchemy async, pytest/httpx).

**Spec:** `docs/superpowers/specs/2026-08-30-member-tree-skeleton-design.md`

## Global Constraints

- `POST /members`, `PUT /members/{id}`, marriage, and avatar endpoints are unchanged — only the two read shapes described here change.
- `GET /members/tree` keeps returning `null` for an empty tree (unchanged behavior, just a smaller node shape when non-null).
- `GET /members/{id}` follows the same 404 pattern as the existing `PUT`/`DELETE` `/members/{id}` handlers (`HTTPException(404, "member not found")`).
- Full test suite (`uv run pytest`) must pass after every task.

---

## File Structure

```
genealogy-api/
  app/
    schemas/member.py     # modified: add MemberSkeletonNode, MemberDetail
    routers/member.py     # modified: _to_skeleton, get_tree response shape, new GET /{member_id}
  tests/
    test_member.py         # modified: drop tree-based detail assertions, add skeleton-shape test
    test_avatar.py           # modified: drop tree-based avatar assertions, add detail-endpoint test
    test_marriage.py           # modified: spouse assertions move from /tree to /members/{id}
```

---

### Task 1: Skeleton `GET /members/tree`

**Files:**
- Modify: `app/schemas/member.py`, `app/routers/member.py`
- Modify: `tests/test_member.py`, `tests/test_avatar.py`, `tests/test_marriage.py`

**Interfaces:**
- Produces: `MemberSkeletonNode` (`app/schemas/member.py`) — `{id: int, name: str, children: list[MemberSkeletonNode]}`, used as `GET /members/tree`'s `response_model` from this task onward.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_member.py` (after `test_create_and_fetch_tree`):

```python
async def test_tree_response_only_has_skeleton_fields(client):
    await _authenticate(client)
    await client.post(
        "/members",
        json={
            "full_name": "Root",
            "parent_id": None,
            "birth_year": 1950,
            "gender": "male",
            "notes": "some notes",
        },
    )

    response = await client.get("/members/tree")
    assert response.status_code == 200
    tree = response.json()
    assert set(tree.keys()) == {"id", "name", "children"}
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_member.py::test_tree_response_only_has_skeleton_fields -v`
Expected: FAIL — `tree.keys()` currently includes `birth_year`, `death_year`, `gender`, `notes`, `avatar_url`, `spouses` too.

- [ ] **Step 3: Add `MemberSkeletonNode` and `MemberDetail` schemas**

In `app/schemas/member.py`, after the `MemberTreeNode` class at the end of the file, add:

```python
class MemberSkeletonNode(BaseModel):
    id: int
    name: str
    children: list["MemberSkeletonNode"] = []


class MemberDetail(BaseModel):
    id: int
    birth_year: int | None = None
    death_year: int | None = None
    gender: Gender | None = None
    notes: str | None = None
    avatar_url: str | None = None
    spouses: list[SpouseInfo] = []
```

- [ ] **Step 4: Add `_to_skeleton` and change `get_tree`'s response shape**

In `app/routers/member.py`, add the import and the helper. Change:

```python
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
from app.schemas.member import (
    MarriageCreate,
    MarriageUpdate,
    MemberCreate,
    MemberDetail,
    MemberRead,
    MemberSkeletonNode,
    MemberTreeNode,
    MemberUpdate,
    SpouseInfo,
)
```

Add, directly after `_build_tree`'s closing `return build(root)` (before `_is_descendant`):

```python
def _to_skeleton(node: MemberTreeNode) -> MemberSkeletonNode:
    return MemberSkeletonNode(
        id=node.id,
        name=node.name,
        children=[_to_skeleton(child) for child in node.children],
    )
```

Change the `get_tree` endpoint:

```python
@router.get("/tree", response_model=MemberTreeNode | None)
async def get_tree(db: AsyncSession = Depends(get_db)) -> MemberTreeNode | None:
    members_result = await db.execute(select(Member))
    members = list(members_result.scalars().all())
    marriages_result = await db.execute(select(Marriage))
    marriages = list(marriages_result.scalars().all())
    return _build_tree(members, marriages)
```

to:

```python
@router.get("/tree", response_model=MemberSkeletonNode | None)
async def get_tree(db: AsyncSession = Depends(get_db)) -> MemberSkeletonNode | None:
    members_result = await db.execute(select(Member))
    members = list(members_result.scalars().all())
    marriages_result = await db.execute(select(Marriage))
    marriages = list(marriages_result.scalars().all())
    full_tree = _build_tree(members, marriages)
    return _to_skeleton(full_tree) if full_tree is not None else None
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `uv run pytest tests/test_member.py::test_tree_response_only_has_skeleton_fields -v`
Expected: PASS

- [ ] **Step 6: Update tests that assumed detail fields on `/members/tree`**

In `tests/test_member.py`, change `test_create_and_fetch_member_with_details`:

```python
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
```

to:

```python
    assert response.status_code == 201
    body = response.json()
    assert body["birth_year"] == 1950
    assert body["gender"] == "male"
```

In `tests/test_avatar.py`, change `test_upload_avatar_replaces_previous_file`:

```python
    assert first.json()["avatar_url"] != second_url
    assert not first_path.exists()

    tree = await client.get("/members/tree")
    assert tree.json()["avatar_url"] == second_url
```

to:

```python
    assert first.json()["avatar_url"] != second_url
    assert not first_path.exists()
```

In `tests/test_avatar.py`, change `test_delete_avatar`:

```python
    response = await client.delete(f"/members/{member_id}/avatar")
    assert response.status_code == 204
    assert not file_path.exists()

    tree = await client.get("/members/tree")
    assert tree.json()["avatar_url"] is None
```

to:

```python
    response = await client.delete(f"/members/{member_id}/avatar")
    assert response.status_code == 204
    assert not file_path.exists()
```

In `tests/test_avatar.py`, delete `test_tree_includes_avatar_url` entirely (Task 2 replaces it with `test_member_detail_includes_avatar_url` against the new endpoint):

```python
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
```

In `tests/test_marriage.py`, change `test_tree_includes_spouse_on_correct_node`:

```python
    response = await client.get("/members/tree")
    tree = response.json()
    assert tree["name"] == "Husband"
    assert len(tree["spouses"]) == 1
    assert tree["spouses"][0]["full_name"] == "Wife"
    assert tree["spouses"][0]["marriage_year"] == 1975
    assert len(tree["children"]) == 1
    assert tree["children"][0]["name"] == "Child"
```

to:

```python
    response = await client.get("/members/tree")
    tree = response.json()
    assert tree["name"] == "Husband"
    assert len(tree["children"]) == 1
    assert tree["children"][0]["name"] == "Child"
```

In `tests/test_marriage.py`, delete `test_tree_supports_multiple_marriages` and `test_deleting_spouse_removes_marriage` entirely (Task 2 replaces both against the new endpoint):

```python
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

- [ ] **Step 7: Run the full suite**

Run: `uv run pytest`
Expected: PASS, 0 failures.

- [ ] **Step 8: Commit**

```bash
git add app/schemas/member.py app/routers/member.py tests/test_member.py tests/test_avatar.py tests/test_marriage.py
git commit -m "feat: shrink GET /members/tree to id/name/children only"
```

---

### Task 2: `GET /members/{id}` detail endpoint

**Files:**
- Modify: `app/routers/member.py`
- Modify: `tests/test_member.py`, `tests/test_avatar.py`, `tests/test_marriage.py`

**Interfaces:**
- Consumes: `MemberDetail` schema from Task 1.
- Produces: `GET /members/{id}` → `MemberDetail`, 404 if the member doesn't exist.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_member.py` (after `test_create_and_fetch_member_with_details`):

```python
async def test_get_member_detail(client):
    await _authenticate(client)
    created = await client.post(
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
    member_id = created.json()["id"]

    response = await client.get(f"/members/{member_id}")
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == member_id
    assert body["birth_year"] == 1950
    assert body["death_year"] == 2010
    assert body["gender"] == "male"
    assert body["notes"] == "Some notes"
    assert body["spouses"] == []


async def test_get_member_detail_defaults_for_bare_member(client):
    await _authenticate(client)
    created = await client.post("/members", json={"full_name": "Bare", "parent_id": None})
    member_id = created.json()["id"]

    response = await client.get(f"/members/{member_id}")
    assert response.status_code == 200
    body = response.json()
    assert body["birth_year"] is None
    assert body["avatar_url"] is None
    assert body["spouses"] == []


async def test_get_member_detail_rejects_nonexistent_member(client):
    await _authenticate(client)
    response = await client.get("/members/9999")
    assert response.status_code == 404
```

Add to `tests/test_avatar.py` (replacing the deleted `test_tree_includes_avatar_url`):

```python
async def test_member_detail_includes_avatar_url(client):
    await _authenticate(client)
    created = await client.post("/members", json={"full_name": "Root", "parent_id": None})
    member_id = created.json()["id"]
    upload = await client.post(
        f"/members/{member_id}/avatar",
        files={"file": ("avatar.jpg", b"data", "image/jpeg")},
    )
    avatar_url = upload.json()["avatar_url"]

    detail = await client.get(f"/members/{member_id}")
    assert detail.json()["avatar_url"] == avatar_url
```

Add to `tests/test_marriage.py` (replacing the deleted multi-marriage and delete-spouse tests):

```python
async def test_member_detail_supports_multiple_marriages(client):
    await _authenticate(client)
    root = await client.post("/members", json={"full_name": "Husband", "parent_id": None})
    root_id = root.json()["id"]
    await client.post(f"/members/{root_id}/marriages", json={"spouse_full_name": "First Wife"})
    await client.post(f"/members/{root_id}/marriages", json={"spouse_full_name": "Second Wife"})

    response = await client.get(f"/members/{root_id}")
    names = {spouse["full_name"] for spouse in response.json()["spouses"]}
    assert names == {"First Wife", "Second Wife"}


async def test_deleting_spouse_removes_marriage(client):
    await _authenticate(client)
    root = await client.post("/members", json={"full_name": "Husband", "parent_id": None})
    root_id = root.json()["id"]
    created = await client.post(f"/members/{root_id}/marriages", json={"spouse_full_name": "Wife"})
    spouse_id = created.json()["id"]

    delete_response = await client.delete(f"/members/{spouse_id}")
    assert delete_response.status_code == 204

    detail_response = await client.get(f"/members/{root_id}")
    assert detail_response.json()["spouses"] == []
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `uv run pytest tests/test_member.py::test_get_member_detail tests/test_member.py::test_get_member_detail_rejects_nonexistent_member -v`
Expected: FAIL — `GET /members/{id}` doesn't exist yet (404 route-not-found or 422, not the intended 200/404 semantics).

- [ ] **Step 3: Implement the endpoint**

In `app/routers/member.py`, add directly after the `get_tree` endpoint (before `@router.post("", ...)`):

```python
@router.get("/{member_id}", response_model=MemberDetail)
async def get_member_detail(member_id: int, db: AsyncSession = Depends(get_db)) -> MemberDetail:
    member = await db.get(Member, member_id)
    if member is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="member not found")

    marriages_result = await db.execute(select(Marriage).where(Marriage.member_id == member_id))
    marriages = list(marriages_result.scalars().all())
    spouses = []
    for marriage in marriages:
        spouse = await db.get(Member, marriage.spouse_id)
        if spouse is not None:
            spouses.append(_spouse_info(marriage, spouse))

    return MemberDetail(
        id=member.id,
        birth_year=member.birth_year,
        death_year=member.death_year,
        gender=member.gender,
        notes=member.notes,
        avatar_url=member.avatar_url,
        spouses=spouses,
    )
```

- [ ] **Step 4: Run the new tests to verify they pass**

Run: `uv run pytest tests/test_member.py tests/test_avatar.py tests/test_marriage.py -v`
Expected: PASS, 0 failures.

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest`
Expected: PASS, 0 failures.

- [ ] **Step 6: Commit**

```bash
git add app/routers/member.py tests/test_member.py tests/test_avatar.py tests/test_marriage.py
git commit -m "feat: add GET /members/{id} for lazy per-member detail"
```
