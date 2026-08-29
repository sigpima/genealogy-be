# Member API — Design Spec

Date: 2026-08-29
Status: Approved for implementation planning

## Context

`genealogy-web`'s family tree currently reads a static, bundled JSON file
(`new_treeData.json`, `{name, children}` shape). This backend has so far
been auth-only (`User`) — see the original backend spec's non-goals. This
spec adds the actual genealogy data: a `Member` model and CRUD API, plus a
one-off script to load the existing static tree into the database so the
displayed tree looks the same once the frontend switches to calling this
API (a separate, frontend-repo spec).

Per this conversation's decision: **one shared family tree for every
logged-in user** — no per-user ownership/multi-tenancy. This is a single
genealogy record multiple people view/edit together, not one tree per
account.

## Goals

- A `Member` model: `id`, `full_name`, `parent_id` (self-referencing,
  nullable — `NULL` means root), `created_at`.
- `GET /members/tree` — the whole tree in the same `{id, name, children}`
  shape (`id` added for a future edit UI) the frontend's `FamilyMember`
  type already structurally accepts.
- `POST /members`, `PUT /members/{id}`, `DELETE /members/{id}` — full
  CRUD, per the earlier discussion (no frontend UI calls these yet this
  round; the backend is ready ahead of that UI, same pattern as the
  original auth phase being ready ahead of this one).
- All Member endpoints require authentication (reuse
  `get_current_user`/`get_token_from_request` from `app/routers/auth.py`)
  — the frontend's own route middleware is not something this API can
  trust as its only gate, since the API is reachable directly too.
- A one-off script that loads `new_treeData.json`'s content into the
  `members` table.

## Non-goals

- Per-user ownership/ACLs on members — one shared tree, per the decision
  above.
- Gender/birth/death/notes fields — the current UI has nothing to
  display them with; add them when a UI need exists.
- Cascading delete of a member's descendants — deleting a member with
  children is rejected (409), not automatically cascaded. Reassigning or
  deleting children first is the caller's job.
- Multiple simultaneous root members — the tree endpoint assumes at most
  one `Member` row has `parent_id IS NULL`; nothing enforces that as a DB
  constraint (no natural single-column constraint expresses it), but
  `POST`/`PUT` validation prevents *creating* a cycle, which is the more
  likely way an edit could actually corrupt the tree.

## Design

**Model (`app/models/member.py`)**:

```python
class Member(Base):
    __tablename__ = "members"

    id: Mapped[int] = mapped_column(primary_key=True)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("members.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
```

No `ondelete` override on the FK — the database's default `NO ACTION`/
`RESTRICT` behavior means attempting to delete a member that other rows
reference as `parent_id` raises an `IntegrityError`, which the delete
endpoint catches and turns into a 409. This is deliberate — it's the
correct "don't cascade-delete descendants" behavior for free, not
something to work around.

**Schemas (`app/schemas/member.py`)**:
- `MemberCreate {full_name: str, parent_id: int | None}`
- `MemberUpdate {full_name: str, parent_id: int | None}` — a full
  replace (PUT semantics), not a partial patch. This sidesteps the
  "was `parent_id` omitted, or explicitly set to `null`?" ambiguity a
  partial-update schema would have; there's no UI consumer yet that
  would benefit from partial updates.
- `MemberRead {id: int, full_name: str, parent_id: int | None, created_at: datetime}`
- `MemberTreeNode {id: int, name: str, children: list[MemberTreeNode]}`
  (recursive) — the shape `GET /members/tree` returns. Field is `name`,
  not `full_name`, to match `FamilyMember`/`new_treeData.json` exactly.

**Router (`app/routers/member.py`)**, all endpoints depending on
`get_current_user` (imported from `app.routers.auth`):
- `GET /members/tree` → `MemberTreeNode | None`, HTTP 200 with a JSON
  `null` body if there are no members yet (not 204 — the response model
  is `MemberTreeNode | None` either way, and a plain `null` is simpler
  for the frontend to branch on than treating an empty body specially).
  Implementation: one query for all members, build
  an `id -> Member` map and an `id -> [children]` map in Python, then
  recursively construct the tree starting from the row with
  `parent_id IS None`. O(n), no recursive SQL needed at this data size.
- `POST /members` → creates a row; if `parent_id` is given, 404 if that
  parent doesn't exist.
- `PUT /members/{id}` → 404 if the member doesn't exist; if `parent_id`
  is given, 404 if that parent doesn't exist, 400 if it equals the
  member's own id or is one of the member's own descendants (walk the
  parent chain from the proposed new parent up to the root — if the
  member being updated is encountered, it's a cycle).
- `DELETE /members/{id}` → 404 if the member doesn't exist; on
  `IntegrityError` from the FK (children still reference it), roll back
  and return 409 with a clear message.

**Seed script (`scripts/seed_members.py`)**: reads a tree JSON file
(`{name, children}` shape) given as a CLI argument, walks it, and inserts
rows via the same async engine/session the app uses, setting `parent_id`
as it goes (root first, then each level). Run once, manually, against
whichever `DATABASE_URL` is active — not part of Alembic migrations
(migrations manage schema, not this kind of one-time data load) and not
run automatically by anything.

## Testing plan

`tests/test_member.py` (new), using the existing `client`
fixture/pattern:
- `GET /members/tree` returns HTTP 200 with a JSON `null` body when
  empty.
- Creating a root then two children, `GET /members/tree` returns the
  correctly nested shape with `id`/`name`/`children`.
- `POST /members` with a non-existent `parent_id` → 404.
- `PUT /members/{id}` changing `full_name` only.
- `PUT /members/{id}` attempting to set `parent_id` to the member's own
  id → 400; attempting to set it to one of its own descendants → 400.
- `DELETE /members/{id}` on a leaf (no children) → succeeds.
- `DELETE /members/{id}` on a member with children → 409.
- All Member endpoints reject requests with no valid auth (401), reusing
  the existing auth test pattern (register/login on the test client
  first for the success-path tests).

## Repo/setup notes

- New Alembic migration for the `members` table (same `alembic revision
  --autogenerate` flow as the `users` table, verified against a real
  Postgres the same way).
- After implementation, re-run the `init` skill to refresh `CLAUDE.md`.
