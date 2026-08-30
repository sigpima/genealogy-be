# Member Tree Skeleton + Per-Member Detail — Design Spec

Date: 2026-08-30
Status: Approved for implementation planning

## Context

`GET /members/tree` currently returns the entire family tree in one
response, and every node carries every field (`birth_year`, `death_year`,
`gender`, `notes`, `avatar_url`, `spouses`) — a deliberate earlier decision
(see `2026-08-29-member-details-design.md`'s Goals: "the tree endpoint is
the only read path the frontend uses, so it needs the full picture in one
response to avoid a second round-trip per member viewed").

That's no longer the right trade-off. `genealogy-web` now renders most
tree nodes name-only, showing full detail (avatar included) only for
members within a small radius of wherever the user is currently focused
(see `genealogy-web`'s `2026-08-30-tree-lod-design.md`). Most of every
`/members/tree` response is now fetched but never rendered. This is the
second of four sub-projects addressing tree-rendering lag on large trees
(see that same spec's Context for the full list); this one is the API
side of "lazy-load tree branches instead of fetching everything at once."

## Goals

- `GET /members/tree` returns only what's needed to draw the tree's shape
  and support name search / reparent-candidate listing client-side: `id`,
  `name` (from `full_name`), and `children` — nothing else.
- A new `GET /members/{id}` returns everything else for one member:
  `birth_year`, `death_year`, `gender`, `notes`, `avatar_url`, `spouses`
  — fetched by the frontend only for members it's actually about to
  render in detail or show in the detail panel.
- Existing tests that assert detail fields via `/members/tree` move to
  asserting them via the new endpoint instead.

## Non-goals

- Changing how `POST /members`, `PUT /members/{id}`, marriage, or avatar
  endpoints work — they're unaffected; only the *read* shape changes.
- Pagination or depth-limiting `/members/tree` itself — the skeleton
  (`id`/`name`/`children` only) is cheap enough at this app's scale that
  sending the whole shape in one response is still fine. Not fetching
  the whole *shape* up front is a bigger change (evaluated in this
  project's brainstorming and explicitly deferred — see the paired
  `genealogy-web` spec's Context for why).
- Any change to how spouses are stored or modeled — `MemberDetail` just
  exposes the same `SpouseInfo` list `MemberTreeNode` already builds.

## Design

**`app/schemas/member.py`** gains two schemas:

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

`MemberTreeNode` stays as-is (still used internally to build both shapes
from the same source data — see below) but is no longer any router's
`response_model`.

**`app/routers/member.py`**:

- `_build_tree` (the existing full-detail builder) is kept, but a new
  `_to_skeleton(node: MemberTreeNode) -> MemberSkeletonNode` recursively
  strips it down. `get_tree` calls `_build_tree` then `_to_skeleton` and
  changes its `response_model` to `MemberSkeletonNode | None`. Building
  the full tree internally and stripping it, rather than writing a
  second from-scratch builder, keeps the root-finding/spouse-exclusion
  logic in exactly one place.
- New endpoint:

```python
@router.get("/{member_id}", response_model=MemberDetail)
async def get_member_detail(member_id: int, db: AsyncSession = Depends(get_db)) -> MemberDetail:
    member = await db.get(Member, member_id)
    if member is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="member not found")

    marriages_result = await db.execute(
        select(Marriage).where(Marriage.member_id == member_id)
    )
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

  Registered after the existing `@router.get("/tree", ...)` (already the
  case, since `/tree` is defined earlier in the file) so FastAPI matches
  the literal `/tree` path before falling through to the `/{member_id}`
  pattern.

## Testing plan

- `GET /members/tree` returns `{id, name, children}` only — no
  `birth_year`/`avatar_url`/`spouses` keys present in the response body,
  even when the underlying members have them set.
- `GET /members/{id}` for a member with no spouses and all detail fields
  `None` returns them as `None`/`[]`.
- `GET /members/{id}` for a member with a spouse returns the spouse in
  `spouses` (marriage id, year, spouse fields) — same shape
  `MemberTreeNode.spouses` already produced.
- `GET /members/{id}` for a nonexistent id returns 404.
- Update `tests/test_member.py`, `tests/test_avatar.py`,
  `tests/test_marriage.py` wherever they currently assert `birth_year` /
  `avatar_url` / `spouses` from a `/members/tree` response — switch those
  assertions to `GET /members/{id}` instead.

## Repo/setup notes

- No migration needed — no model/column changes, only response shapes.
- After implementation, re-run the `init` skill to refresh `CLAUDE.md`.
