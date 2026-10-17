# GĐ6 — Media library and places (lăng mộ, nhà thờ, map) — Design

Date: 2026-10-18
Status: Approved to build by the owner ("tiếp tục với giai đoạn 6"); realises roadmap K + G. The choices below are mine
where the owner did not specify.

## Goal

Give each person a shelf of photos and scanned documents ("Tư liệu & bút tích"), and turn the free-text "mộ phần" field into
real **places** (nhà thờ họ, từ đường, lăng mộ, nghĩa trang, đền) on a map, each with the people resting there.

## Media

`media(tree_id, member_id | place_id, kind image|document, original_name, content_type, size, width, height, stored name,
thumbnail name, caption, uploaded_by, created_at)`; files on disk under `UPLOAD_DIR/media/` (+ `thumbs/`), random UUID names.

- Accepted: JPEG, PNG, WebP images and PDF documents, up to **10 MB**. The **content is checked, not only the declared type**
  (Pillow must open an image; a PDF must start with `%PDF-`), so a renamed file is refused.
- Images get a 480 px **thumbnail** (EXIF rotation applied to it; the original is kept untouched).
- Only **admins** upload, caption and delete (members already have the change-request door for facts; photo proposals are a
  later phase). Deleting a person or place removes their files too.
- **Who can see them:** signed-in users of the tree and the superadmin. **Not guests of a public tree** — scans of certificates
  and graves are the kind of thing the owner redacts from guests (notes, burial info); per-item privacy comes with GĐ11. Files are
  served through the API with the tree check, like avatars (`/uploads/media/<name>`, `/uploads/media/thumbs/<name>`), 404 otherwise.
- Every upload, caption change and deletion is audit-logged.

## Places

`places(tree_id, kind clan_house|temple|tomb|cemetery|other, name, address, latitude, longitude, description, caretaker,
visit_notes)`. GPS is both-or-neither. Signed-in users only (a grave's location is burial information).

- `members.burial_place_id` (→ places, `ON DELETE SET NULL`) and `members.burial_plot` ("khu B, hàng 3, mộ 12") give a person
  their resting place. The old `burial_place` text and GPS fields stay; they are not removed.
- `GET /places` lists places with how many people rest there; `GET /places/{id}` adds the **residents** (name, plot, years).
- **Migration of the old field** (`POST /places/migrate-burials`, admin, `dry_run` first): people with a `burial_place` text and no
  place yet are grouped by the text ignoring case/diacritics/spacing; one `tomb` place per group (GPS from the first person who
  has coordinates), and the people are linked. Idempotent: anyone already linked is skipped.
- Events can point at a place (`events.place_id`), so "giỗ Tổ ở nhà thờ" shows the place on the calendar.
- `burial_place_id`/`burial_plot` are admin-only fields: they are **not** proposable through change requests.

## Frontend

- Panel: "Tư liệu & bút tích" gallery (thumbnails, viewer, PDFs open in a tab; admins upload, caption, delete) and "An nghỉ" (place,
  plot, directions link; admins choose place and plot in the edit form).
- `/dia-diem`: list + filter by kind + an OpenStreetMap map (Leaflet, no API key) with a marker per place; place page/drawer with
  address, caretaker, visit notes, residents, photos, "Chỉ đường" (Google Maps); admins add/edit/delete places (pick the point by
  clicking the map) and run the migration with a preview.

## Non-goals (later)

Photo proposals from members, albums/tags/faces, drag-to-reorder, storage quotas, MinIO/object storage, per-item privacy (GĐ11),
videos/audio, a place hierarchy (khu → hàng → mộ as records), offline map tiles.
