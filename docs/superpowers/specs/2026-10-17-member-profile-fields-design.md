# Member Profile Fields — Design

Date: 2026-10-17
Status: Approved to build by the owner ("thêm dữ liệu từ bản thiết kế"); field list below is my proposal.

## Why

The Heritage Tree UI design (`/design/`) shows information the database has no
place for: courtesy name (tên tự), title (chức vị), birth rank (Trưởng/Thứ/Út),
residence, and burial place with GPS. The frontend redesign deliberately left
these out ("no invented data"). This adds the data so the UI can show and edit it.

## Scope

New nullable columns on `members` (one Alembic migration):

| column | type | meaning |
|---|---|---|
| `courtesy_name` | `String(100)` | tên tự |
| `title` | `String(150)` | chức vị / tước vị |
| `residence` | `String(255)` | nơi ở / quê quán |
| `burial_place` | `String(500)` | mộ phần (free text) |
| `burial_latitude` | `Float` | GPS, -90..90 |
| `burial_longitude` | `Float` | GPS, -180..180 |

Rules (my calls):
- Blank / whitespace-only strings are stored as `NULL`; values are stripped.
- Latitude and longitude are both-or-neither, range-checked (422 otherwise).
- `PUT /members/{id}` stays a full replacement: omitted new fields become `NULL`
  (the frontend must send every field). Same behaviour as the existing fields.
- `MemberRead` (create/update responses) and `MemberDetail` (`GET /members/{id}`)
  include the six fields. `GET /members/tree` stays skeleton-only (`id`, `name`, `children`).
- `MemberDetail` also gets a **computed**, not stored, `sibling_rank: str | None`:
  among members with the same `parent_id` and the same gender (`male`/`female`),
  ordered by `birth_year` (unknown last) then `id`: first → `Trưởng nam`/`Trưởng nữ`,
  last (when there are 2+) → `Út nam`/`Út nữ`, otherwise `Thứ nam`/`Thứ nữ`.
  `None` for a root member, a member with no/`other` gender. Spouses are not siblings.

## Frontend (genealogy-web)

- `MemberDetail` type gains the new fields + `sibling_rank`.
- Panel, tab "Tiểu sử": a "Thông tin" list (Tên tự, Chức vị, Nơi ở, Mộ phần with a
  maps link when GPS is present); the edit form edits all six fields (both GPS or neither,
  checked client-side too). Header shows the rank next to the generation badge.
- Detailed tree card shows the rank next to the "Đời N" badge. No other card changes.
- `PUT` body always carries all fields.

## Non-goals

- "Tư liệu & bút tích" gallery (documents/photos), Sử ký, Lăng mộ pages, Lịch giỗ: separate projects.
- Spouse profile fields (only members get the new fields; a spouse is a member row but
  the spouse forms stay as they are).
- Auto-translating or validating the free text.
