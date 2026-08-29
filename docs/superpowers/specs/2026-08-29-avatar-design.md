# Member Avatar Photo — Design

## Goal

Let a tree member (not a spouse — see Scope) have an optional avatar
photo. The photo is shown as a small circular thumbnail on the
member's tree node and as a larger image in the member detail panel.
Uploading, replacing, and removing the photo happens from the same
"Sửa" (edit) form already used for the member's other fields.

## Scope

- Only top-level tree members (`Member` rows reached via the
  `parent_id` chain) get an avatar in this iteration — `SpouseInfo`
  does not gain an `avatar_url` field. Spouses are still full `Member`
  rows and the upload endpoint works on any member id, but no frontend
  UI exposes uploading a spouse's photo yet. This keeps the already
  fairly complex spouse-row UI (added in the marriage feature) out of
  scope for this change.
- No image cropping/resizing UI — whatever file the browser produces
  from the file picker is stored as-is (subject to the size/type
  validation below). Client-side or server-side resizing is future
  work if file sizes become a problem in practice.

## Data model

`Member` (`app/models/member.py`) gains:

```python
avatar_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
```

Nullable, like every other optional detail field on this model. Stores
a path such as `/uploads/avatars/<uuid>.jpg` — never an absolute URL
with a host, so the frontend can proxy it the same way it proxies
`/api/*` (see Frontend section).

## File storage

Uploaded files are written to local disk under a directory controlled
by a new setting:

```python
# app/core/config.py
upload_dir: str = "uploads"
```

Avatars are saved to `<upload_dir>/avatars/<uuid4()><ext>` where `<ext>`
is derived from the validated content type (`.jpg`, `.png`, or
`.webp`). `<upload_dir>` defaults to `uploads` (relative to the
process's working directory, matching how `alembic`/`scripts/
seed_members.py` already resolve paths relative to `os.getcwd()`), and
tests override it via `monkeypatch.setenv("UPLOAD_DIR", ...)` pointed
at a pytest `tmp_path`, so test runs never write into the repo's real
`uploads/` folder. `uploads/` is added to `.gitignore` — uploaded
content is runtime data, not source.

`app/main.py` mounts the directory for static serving:

```python
app.mount("/uploads", StaticFiles(directory=settings.upload_dir), name="uploads")
```

## Validation

- Allowed content types: `image/jpeg`, `image/png`, `image/webp`.
  Anything else → `400 Bad Request`.
- Max size: 5 MB, checked against the actual uploaded byte length (not
  a trusted `Content-Length` header) → `400 Bad Request` if exceeded.

## API

**`POST /members/{member_id}/avatar`** (multipart/form-data, field name
`file`)
- 404 if `member_id` doesn't exist.
- 400 for a disallowed content type or a file over 5 MB.
- Saves the new file, deletes the member's previous avatar file from
  disk if one existed (best-effort — a missing file on disk is not an
  error), updates `Member.avatar_url`, commits.
- 200, returns `{"avatar_url": "/uploads/avatars/<uuid>.jpg"}`.

**`DELETE /members/{member_id}/avatar`**
- 404 if `member_id` doesn't exist.
- Deletes the file from disk (best-effort) and sets `avatar_url =
  NULL`.
- 204, no body.

Both routes live in the existing `app/routers/member.py` and inherit
the router's `dependencies=[Depends(get_current_user)]`.

`MemberRead` and `MemberTreeNode` (`app/schemas/member.py`) both gain
`avatar_url: str | None`. `_build_tree`'s `build()` passes
`avatar_url=node.avatar_url` alongside the other fields it already
copies.

## Frontend

**Proxying static files:** `next.config.ts`'s `rewrites()` gains a
second rule, `/uploads/:path*` → `${API_BASE_URL}/uploads/:path*`,
mirroring the existing `/api/:path*` rule. This lets `<img src="/uploads/...">`
stay relative — no hardcoded backend origin, consistent with why the
`/api` proxy exists in the first place (see the "same-origin proxy"
note in `genealogy-web/CLAUDE.md`).

**Types:** `FamilyMember` (`src/lib/tree/types.ts`) gains `avatar_url?:
string | null`.

**Tree node rendering** (`renderNode` in `genealogy-tree/page.tsx`):
each node shows a small circular thumbnail (via an SVG `<clipPath>` +
`<image>`) to the left of the name when `avatar_url` is present;
otherwise a plain circle showing the member's first initial, so every
node has a consistent visual anchor whether or not a photo was
uploaded.

**`MemberDetailPanel`:**
- Display mode shows a larger version of the same circular
  image/initial at the top of the panel, above the name.
- Edit mode gains a file input (`accept="image/*"`) below the name
  field, plus a "Xoá ảnh" button shown only when an avatar currently
  exists (either already saved, or just picked in this edit session).
  Picking a file shows an immediate local preview (`URL.createObjectURL`)
  without uploading yet.
- On "Lưu": if the user removed the avatar (clicked "Xoá ảnh") without
  picking a replacement, call `DELETE /api/members/{id}/avatar` first.
  Else if a new file was picked, call `POST /api/members/{id}/avatar`
  first (multipart) and read the returned `avatar_url`. Either way,
  once that settles (or if neither happened), send the existing JSON
  `PUT /api/members/{id}` for the other fields, same as today. This
  keeps the general member-update JSON contract untouched — only the
  avatar sub-resource uses multipart.

## Testing

Backend (pytest):
- Model: `Member.avatar_url` defaults to `None`, accepts a string.
- Router, using a `tmp_path`-backed `UPLOAD_DIR` (monkeypatched per
  test):
  - Uploading a valid JPEG/PNG sets `avatar_url` and the file exists
    on disk at that path.
  - Uploading again for the same member replaces `avatar_url` and
    removes the old file.
  - Rejects a disallowed content type (400).
  - Rejects a file over 5 MB (400).
  - 404 for a nonexistent member.
  - `DELETE` clears `avatar_url` and removes the file; 404 for a
    nonexistent member.
  - `GET /members/tree` includes `avatar_url` on the correct node.
  - Avatar routes reject unauthenticated requests (401).

Frontend: no new Vitest coverage (avatar handling is UI wiring, not
pure logic) — verified via `tsc --noEmit` + `eslint` + a real-browser
Playwright pass: upload a photo, confirm it renders on both the tree
node and the panel, replace it with a different photo, remove it, and
confirm the tree node falls back to the initial-letter circle.
