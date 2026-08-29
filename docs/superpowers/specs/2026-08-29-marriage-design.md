# Marriage (Spouse Relationships) — Design

## Goal

Let a member of the shared family tree have one or more recorded
marriages over time (supporting remarriage). A spouse is a full
`Member` record (so they can carry their own birth/death year, gender,
notes) but is not part of the blood-line tree: their `parent_id` is
always `NULL` and they never have children of their own in this
system — a couple's children continue to link to a single blood-line
parent via `parent_id`, exactly as today. Spouse information is shown
only in the member detail panel on the frontend, never as a node on the
tree itself.

## Data model

New table `marriages`:

| column         | type      | notes                                   |
|----------------|-----------|------------------------------------------|
| `id`           | int PK    |                                          |
| `member_id`    | int FK → `members.id`, `ON DELETE CASCADE` | the blood-line member |
| `spouse_id`    | int FK → `members.id`, `ON DELETE CASCADE` | the spouse (a `Member` with `parent_id = NULL`) |
| `marriage_year`| int, nullable | year-only, matches `birth_year`/`death_year` convention |
| `created_at`   | timestamptz, server default `now()` |                     |

Both FKs cascade on delete: deleting either party in a marriage removes
the marriage row automatically — no application-level cleanup needed.
This mirrors the existing `birth_year`/`death_year`-are-nullable-ints
convention rather than introducing a new modeling style.

A spouse `Member` is otherwise a completely ordinary row in `members`
— same table, same fields, same `MemberRead` shape when fetched
directly. What makes it "a spouse" rather than "the tree root" is
purely that some `marriages` row references it as `spouse_id`.

**`_build_tree` root-selection change:** today, root selection is
`root_candidates = children_by_parent.get(None, [])`, `root =
root_candidates[0]`. Once spouses exist, more than one member can have
`parent_id = NULL` (the true root, plus every spouse). Root selection
must exclude any member id that appears as a `spouse_id` in
`marriages`:

```python
spouse_ids = {m.spouse_id for m in all_marriages}
root_candidates = [
    m for m in children_by_parent.get(None, [])
    if m.id not in spouse_ids
]
root = root_candidates[0]
```

This assumes exactly one true root exists among the non-spouse,
parent-less members — the existing invariant for this shared tree,
unchanged by this feature.

**Tree node shape:** each `MemberTreeNode` gains a `spouses: list[SpouseInfo]`
field, populated by grouping `marriages` by `member_id` (a member's
spouses, not the reverse — a member is never looked up as someone
else's spouse for this purpose, since spouses never appear as
standalone tree nodes to attach their own `spouses` list to).

```python
class SpouseInfo(BaseModel):
    marriage_id: int
    marriage_year: int | None
    id: int  # the spouse's own Member id
    full_name: str
    birth_year: int | None
    death_year: int | None
    gender: Gender | None
    notes: str | None
```

Fetching the whole tree in one request already means fetching every
member; `marriages` for the whole tree is one extra query (`SELECT *
FROM marriages`), grouped in Python the same way `_build_tree` already
groups `members` by `parent_id`. No N+1 queries.

## API

Reuses the existing `Member` CRUD wherever possible rather than growing
a parallel set of relationship endpoints (per the standing "don't add
relationship/ownership concepts without a real UI need" guidance —
here the need is real, but the *editing/deleting* of a spouse's own
fields is still just editing/deleting a `Member`).

**`POST /members/{member_id}/marriages`** — create a marriage and its
spouse member in one call (they are always created together — there is
no flow for marrying two pre-existing tree members to each other).

Request:
```json
{
  "spouse_full_name": "string, required",
  "spouse_birth_year": 1950,
  "spouse_death_year": null,
  "spouse_gender": "female",
  "spouse_notes": null,
  "marriage_year": 1975
}
```
- 404 if `member_id` doesn't exist.
- 422 if `spouse_death_year < spouse_birth_year` (reuse the same
  `model_validator` pattern as `MemberCreate`/`MemberUpdate`).
- Creates the spouse as a new `Member(parent_id=None, ...)`, then a
  `Marriage` row linking them, in one transaction.
- 201, returns `SpouseInfo`-shaped body (includes `marriage_id`).

**`PUT /members/marriages/{marriage_id}`** — update `marriage_year` and
the spouse's own editable fields together (mirrors how the frontend's
member-edit form submits everything in one `PUT`).

Request:
```json
{
  "spouse_full_name": "string, required",
  "spouse_birth_year": 1950,
  "spouse_death_year": 2020,
  "spouse_gender": "female",
  "spouse_notes": "string or null",
  "marriage_year": 1975
}
```
- 404 if `marriage_id` doesn't exist.
- 422 on bad years, same rule as create.
- Updates the `Marriage.marriage_year` and the linked spouse `Member`'s
  fields directly (no re-parenting logic needed — a spouse's
  `parent_id` is never touched by this endpoint).
- 200, returns the updated `SpouseInfo`.

**Deleting a marriage** — no new endpoint. The frontend calls the
existing `DELETE /members/{spouse_id}`. The FK's `ON DELETE CASCADE`
removes the `marriages` row as a side effect. This endpoint's existing
`IntegrityError` → 409 handling (today used for "member has children")
still applies unchanged — a spouse is not expected to have children of
their own, so this path should not normally trigger for a spouse, but
if it somehow did (e.g. data entered outside the normal flow), the
existing 409 behavior is the correct, already-tested response; no new
test is required to prove that path for the marriage feature
specifically.

All new routes live under the existing `member` router
(`app/routers/member.py`) and inherit its router-level
`dependencies=[Depends(get_current_user)]` — no separate auth wiring
needed.

## Frontend

`FamilyMember` (`src/lib/tree/types.ts`) gains:
```ts
export type Spouse = {
  marriageId: number;
  marriageYear: number | null;
  id: number;
  name: string;
  birthYear: number | null;
  deathYear: number | null;
  gender: Gender | null;
  notes: string | null;
};

export type FamilyMember = {
  // ...existing fields
  spouses?: Spouse[];
};
```
(API field names are snake_case per the established convention for
this type; the panel-facing camelCase conversion happens in
`genealogy-tree/page.tsx`, same as the existing birth/death/gender/notes
fields.)

`MemberDetailPanel` gains a "Vợ/chồng" section, below the existing
children section:
- Lists each spouse as a row: name, lifespan (reusing the same
  `"{birth} – {death|nay}"` formatting already used for the member
  themself), marriage year if present, gender label if present.
- Each row has "Sửa" and "Xoá" actions.
  - "Sửa" expands that row into the same shape of form used for
    editing the member themself (name, birth year, death year, gender,
    notes) plus a marriage-year field, with its own Save/Cancel —
    submits one `PUT /members/marriages/{marriageId}`.
  - "Xoá" confirms (`window.confirm`, matching the existing
    delete-member confirmation), then calls `DELETE
    /members/{spouseId}` and removes the row from local state on
    success.
- A simple "Thêm vợ/chồng" form below the list: name + marriage year
  only (mirrors the add-child form's minimalism) — submits `POST
  /members/{memberId}/marriages` with just `spouse_full_name` and
  `marriage_year`; the richer fields (birth/death/gender/notes) are
  filled in later via that spouse row's own "Sửa".

No changes to the tree rendering (`renderNode` in
`genealogy-tree/page.tsx`) or to `react-d3-tree` usage — spouses are
never tree nodes.

## Testing

Backend (`genealogy-api`, pytest):
- Model: a `Marriage` row can be created and its FKs resolve.
- Schema: `SpouseInfo` validation, year-order rejection on create and
  update.
- Router:
  - `POST /members/{id}/marriages` creates both the spouse member and
    the marriage row; 404 for nonexistent `member_id`; 422 for bad
    years.
  - `GET /members/tree` includes `spouses` on the correct node, and
    the spouse member itself does **not** appear as a second root or
    anywhere else in the `children` structure.
  - Two remarriages for the same member both appear in that member's
    `spouses` list (covers the "multiple marriages over time" choice).
  - `PUT /members/marriages/{id}` updates both `marriage_year` and the
    spouse's own fields; 404 for nonexistent `marriage_id`.
  - `DELETE /members/{spouse_id}` removes the spouse and its marriage
    row (verified via a subsequent `GET /members/tree` no longer
    showing that spouse).
  - All marriage routes reject unauthenticated requests (401), same as
    the rest of `/members/*`.

Frontend (`genealogy-web`):
- No new Vitest coverage needed — `src/lib/tree/search.ts`'s pure
  functions are untouched by this feature (spouses are not part of the
  parent/child path search), and the panel's spouse UI is exercised the
  same way the rest of `MemberDetailPanel` is: manual + Playwright
  verification in a real browser (add a spouse, edit a spouse, delete a
  spouse, confirm the tree/panel refresh behavior — silent refetch,
  `ancestorPath` staleness — still holds, per the two gotchas already
  documented in `genealogy-web/CLAUDE.md`).
