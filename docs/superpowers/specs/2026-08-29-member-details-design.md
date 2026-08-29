# Member Details (birth/death year, gender, notes) — Design Spec

Date: 2026-08-29
Status: Approved for implementation planning

## Context

`Member` currently has only `full_name` and `parent_id` — enough to draw the
tree shape, not enough to actually be useful as a genealogy record. Per
this conversation's decision, four optional fields are added: birth year,
death year, gender, and free-text notes (occupation etc. goes in notes
rather than getting its own column).

## Goals

- `Member` gains `birth_year`, `death_year`, `gender`, `notes` — all
  nullable (a real family tree rarely has complete data for everyone).
- `POST /members` and `PUT /members/{id}` accept all four; `GET
  /members/tree` returns them on every node (not just `GET /members/{id}`,
  which doesn't exist — the tree endpoint is the only read path the
  frontend uses, so it needs the full picture in one response to avoid a
  second round-trip per member viewed).
- Reject a `death_year` earlier than `birth_year` when both are given —
  contradictory data.

## Non-goals

- Full dates (day/month) — per the earlier decision, year-only matches
  how this data actually exists in practice (old genealogy records rarely
  have more), and avoids date-picker/partial-date UI complexity.
- A dedicated `occupation` field — folded into `notes`.
- Any UI for these fields — that's the paired frontend spec.
- Lunar-calendar year handling — plain Gregorian integer year.

## Design

**Model (`app/models/member.py`)** gains:

```python
birth_year: Mapped[int | None] = mapped_column(nullable=True)
death_year: Mapped[int | None] = mapped_column(nullable=True)
gender: Mapped[str | None] = mapped_column(String(10), nullable=True)
notes: Mapped[str | None] = mapped_column(Text, nullable=True)
```

`gender` is a plain `String(10)` column, not a Postgres native `ENUM` type
— validation lives at the Pydantic layer (see below), consistent with
this codebase's existing "Pydantic validates, SQLAlchemy just stores"
boundary rule. A native DB enum would also be more painful to extend
later (adding a value requires an `ALTER TYPE`, not just an app-level
change) for no real benefit at this scale. `notes` is `Text` (unbounded),
not `String(255)` — free-text notes shouldn't have an arbitrary length
cap.

**Gender values (`app/schemas/member.py`)**: a `Gender(str, Enum)` with
`male`, `female`, `other`. Both `MemberCreate` and `MemberUpdate` validate
`death_year >= birth_year` when both are present (a `@model_validator`
on each — small enough duplication that factoring it out isn't worth a
shared base class here).

**`MemberTreeNode`** gains the same four fields (all optional, default
`None`), populated by `_build_tree` from the corresponding `Member`
columns. `MemberCreate`/`MemberUpdate`/`MemberRead` also gain them.

**Router (`app/routers/member.py`)**: `create_member` passes the four new
fields through to `Member(...)`; `update_member` assigns them the same
way it already assigns `full_name`/`parent_id` (full-replace semantics,
same as the rest of `MemberUpdate` — a field left out of the request
becomes `None`, matching how `parent_id`/`full_name` already work).

## Testing plan

- Schema tests: `MemberCreate`/`MemberUpdate` accept all four fields;
  reject `death_year < birth_year`; reject an invalid `gender` string;
  accept all fields being omitted (all `None`).
- Model test: a `Member` row round-trips `birth_year`/`death_year`/
  `gender`/`notes` correctly (including all-`None`).
- Router tests: `POST /members` with full details, then `GET
  /members/tree` reflects them on that node; `PUT /members/{id}`
  changing details; `PUT` with `death_year` before `birth_year` → 400.

## Repo/setup notes

- New Alembic migration adding the four nullable columns to `members`.
- After implementation, re-run the `init` skill to refresh `CLAUDE.md`.
