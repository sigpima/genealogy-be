# Feedback batch (19/10/2026): editor, generation stepper, header, media, data-entry cards, spouse/adoption, burial map link, invitations — Design

Date: 2026-10-19
Status: Draft for the owner's approval. The owner gave 8 pieces of feedback after trying the app and asked for a plan; the frontend redesigns
follow the ui-ux-pro-max pass (its database only had generic matches here: visible labels, `type=url`/`number` inputs, 44px targets, icon buttons need
accessible names, progress/feedback for uploads, no hover-only information; nothing specific to rich-text toolbars, so that part is my own design).
Everything not marked **[owner]** is my call.

## What the owner asked, and what I found

| # | Feedback | Finding in the current app | Decision |
|---|---|---|---|
| 1 | Chronicle editor should not be Markdown; modern, Google-Docs-like toolbar, select text and apply | `ArticleEditor` is a Markdown textarea; articles are stored as Markdown and read by a safe renderer and by the book PDF | **WYSIWYG editor that still stores Markdown** (Phase 3) |
| 2 | Generation picker on the tree is a row of chips; many generations force scrolling; make it a number input with +/− | `GenerationFilterBar`: one chip per generation, "+N đời" overflow; click = show generations 1..N | **Stepper**: value = deepest generation shown; range 1..youngest (whole tree) or branch-root generation..youngest (branch view) (Phase 1) |
| 3 | Should a system user and a family member be linked? A user who registers from the family's link sees their tree, right? | Registering through the family link put the account in that family; the link to a *person* was only a manual, display-only link set by an admin (`users.member_id`) | **Yes — via invitation links, and public sign-up is removed** (Phase 4, decided by the owner) |
| 4 | Header: name to the left; notifications, sign-out and settings all icons at the far right | Name sits next to the right-hand group; sign-out is text | Redesign (Phase 1) |
| 5 | "Tư liệu & bút tích": native file input ("Choose file / No file…") and photos piled up, confusing | `MediaGallery` with a bare `<input type=file>` | Redesign upload + gallery (Phase 2) |
| 6 | Where do I add a spouse? And the founding ancestor can be marked "con nuôi"? | Spouses are added in the profile panel's tab **"Hôn phối & con"** (admins only), easy to miss. The "Con nuôi" checkbox shows for everybody, root included, and the API accepts `is_adopted` with no father | Make "Thêm vợ/chồng" / "Thêm con" visible actions on the panel; hide "Con nuôi" for the root and make the API refuse it (Phase 1) |
| 7 | Data-entry: replace the single progress line with one fixed card per filter ("120/810 có giới tính"), 2 rows of 3+2 | One progress bar (gender + birth year) and a text line | Five cards, each clickable = applies that filter (Phase 1) |
| 8 | Burial: nobody knows exact coordinates; just attach a Google Maps link | Burial/place forms ask for latitude and longitude | Paste a **Google Maps link**; coordinates are derived from it when the link carries them (Phase 2) |

## Goals

- An admin writes a chronicle like a document: toolbar with icons, select text and apply, no Markdown visible; existing articles open unchanged.
- The tree's generation control stays one compact control however many generations exist.
- Header, media area and data-entry progress are clear at a glance on a phone for an elderly relative.
- Nobody types coordinates; a burial can be found with one tap.
- A relative invited by the admin lands in the tree as *themselves*.

## Non-goals

- Tables, colours, fonts or font sizes in chronicles (Markdown cannot hold them; headings, bold, italic, lists, quote, rule, link and photo are enough for a family history).
- Real-time co-editing, comments or version history of articles.
- Parsing short Google links (`maps.app.goo.gl/...`) into coordinates (a browser cannot read them across origins; the link is stored and opens in Maps; the map pin appears only when the pasted URL carries coordinates).
- Changing who can see or edit what (privacy levels, roles) beyond Phase 4's invitation and the removal of public sign-up.

## Anti-goals (a failure even if it technically works)

- An existing article loses or garbles content when opened and saved in the new editor (Markdown round-trip must be lossless for what the app supports).
- Pasted Google Maps links used as an XSS/open-redirect vector (only `https` links to Google Maps hosts are stored; displayed with `rel=noopener`).
- The stepper hiding people (typing a depth below the branch root or above the youngest generation).
- An invitation link granting more than "member of this family, linked to one person".

## Phase 1 — quick fixes (header, generation stepper, data-entry cards, spouse/adoption)

**Header (`Header.tsx`).** Left: menu button (phone), family name, then the user's name and role as a small block next to the family name on wide
screens (on phones the name goes into the account menu's label). Right-aligned group, all icon buttons with `aria-label`/visible tooltip text, 44×44px:
tree switcher (superadmin, unchanged), notifications bell (unchanged), **settings (theme) icon**, **sign-out icon**. Guests keep a text "Đăng nhập" link. Same on every page that uses the header.

**Generation stepper (`GenerationFilterBar`).** A compact control on the tree: label "Hiển thị đến đời", `−` button, a number input (`inputmode=numeric`, `aria-label`), `+` button,
and a caption "trên tổng N đời" (and "từ đời K" when viewing one branch). Value = the deepest generation shown (today's chip semantics: generations 1..N open, deeper collapsed).
Range: `min` = 1 (whole tree) or the branch root's generation (branch/ancestor view), `max` = the youngest generation present. Typing is clamped on blur/Enter; ArrowUp/Down step; default = `max`
(everything shown) — a change from today's default of 4 generations, as the owner described ("mặc định từ 1 đến đời trẻ nhất"); a *very large* tree (> 2,000 people) keeps the
old default of 4 so the first paint stays light (**[my call]**, shown in the caption). The per-generation head-counts leave this bar (they remain in the statistics page).

**Data-entry cards (`DataEntry.tsx`, `GET /members/completeness`).** Five fixed cards, one per "missing" filter — Giới tính, Năm sinh, Quê quán, Năm mất, Ảnh đại diện — laid out 3 + 2 (2 + 2 + 1 on a phone, 1 column under 360px).
Each: icon, "120/810", label "đã có giới tính", a thin progress bar and, for Năm mất, the caption "người còn sống không có năm mất". Pressing a card toggles that "thiếu …" filter (same as the chips today, which stay as the
precise control with the generation/search inputs). API: `Completeness` gains `with_death_year` and `with_avatar`.

**Spouse and adoption.** The profile panel gets two admin-only quick actions under the name — "＋ Thêm vợ/chồng" and "＋ Thêm con" — that open the existing add forms (tab "Hôn phối & con" scrolled to them).
The "Con nuôi" checkbox is **hidden for a person without a father (the root)** and the API answers 422 for `is_adopted=true` without `parent_id` (create, PUT, PATCH, CSV import, change requests).
Existing rows: a one-off check at migration time lists (does not change) root members flagged adopted; the note for the owner reports how many.

## Phase 2 — media area and burial map link

**"Tư liệu & bút tích" (`MediaGallery`).** An "Thêm ảnh hoặc tài liệu" primary button (hidden file input behind it, also drag-and-drop on wide screens, multiple files), a per-file progress/status row
("Đang tải 2/3…", success tick, error with the reason: type/size), then a **grid of cards**: each card has a fixed-aspect thumbnail (documents show a PDF tile with the file name), caption below, and a ⋯ menu
(Sửa chú thích / Xoá, admin only) so nothing overlaps; tapping a card opens the existing viewer. Photos and documents are two labelled groups ("Ảnh", "Tài liệu"). Empty state explains what belongs here.
Members (non-admin) see the grid without upload/menu.

**Burial and places.** The member form's "Vĩ độ mộ / Kinh độ mộ" and the place form's latitude/longitude inputs are replaced by one field **"Link Google Maps"** (`type=url`, helper "Mở Google Maps, bấm Chia sẻ → Sao chép liên kết, dán vào đây"),
with a "Mở trên Google Maps" link once saved. Storage: new nullable `members.burial_map_url` and `places.map_url` (≤ 500 chars). Validation (backend, `app/core/map_links.py`): scheme `https`, host in
`google.com`, `www.google.com`, `maps.google.com`, `maps.app.goo.gl`, `goo.gl` (path `/maps…`), `g.co` forbidden — anything else is 422. A pure function `coordinates_from(url)` extracts `lat,lng` from
`@lat,lng`, `!3dLAT!4dLNG`, `?q=lat,lng` / `?ll=lat,lng` (and `/maps/place/<lat>,<lng>`); when found, the **existing** `latitude/longitude` columns are filled from it (so the places map keeps working), when not they are left alone.
Old coordinates keep displaying and a "Xem trên bản đồ" link is built from them; they can be cleared by clearing the link field. Change requests/proposals: `burial_map_url` is admin-only like the other burial fields.

## Phase 3 — chronicle editor (WYSIWYG, stored as Markdown)

New editor component built on **Tiptap** (ProseMirror) with a Markdown serializer, so `articles.body` stays Markdown: the safe renderer (`MarkdownView`), the book PDF (`app/core/book.py`) and old articles are untouched.
- **Toolbar** (sticky, icon buttons with names, 44px, wraps on phones): Hoàn tác, Làm lại | Tiêu đề lớn, Tiêu đề nhỏ, Đoạn văn | **B** In đậm, *I* In nghiêng | Danh sách chấm, Danh sách số | Trích dẫn | Đường kẻ | Chèn link | Chèn ảnh (picks from the article's uploaded photos, as today). Buttons show the active state (`aria-pressed`) for the selection, so "select text, press a button" and "press, then type" both work. Keyboard shortcuts (Ctrl/Cmd+B, I, K) and Markdown-style shortcuts while typing (`## ` etc.) stay available but are never required or shown.
- **Link dialog** (URL + text), only `http(s)`/`mailto` accepted. **Image**: inserts the picker's photo; the node serializes to the existing `![alt](media:ID)` form the renderer expects.
- Saving/loading: `markdown → editor → markdown` must be **lossless for the supported subset** (tested on every construct and on the real articles' bodies); unsupported Markdown (raw HTML, tables, code blocks) is kept as plain paragraphs of text rather than dropped, and the editor warns once ("Một số định dạng cũ được hiển thị như văn bản thường").
- The editing page keeps a live "Xem trước" toggle (the real reader view) and the existing draft/published, cover, pinned and "người được nhắc" controls.
- Dependency note: adds `@tiptap/*` packages and a Markdown serializer to `genealogy-web` (build size noted in the report; the editor is loaded lazily only on the edit pages).

## Phase 4 — invitation links, and no more public sign-up **[owner decided, 19/10]**

**Decision of the owner:** accounts come from only two doors. The owner creates the first superadmin from the command line; the superadmin creates a family together with its first admin;
the admin then invites relatives with **a link bound to one person of the tree**. There is no public sign-up. The admin is also a member of the family: after the data is entered the admin links their own
account to their person **themselves** (no superadmin approval — the link is display-only, grants nothing, and is already in the family's audit log as `user.update`).

**Invitations.** New table `invitations(id, tree_id, member_id → members CASCADE, token_hash (sha256, unique), created_by SET NULL, created_at, expires_at (14 days), used_at, used_by SET NULL, revoked_at)`.
- Admin (tree-scoped, audited `invite.create|revoke`): `POST /members/{id}/invitation` → `{path: "/moi/<token>", expires_at}` — **the raw token is shown once** (only its hash is stored, like password-reset tokens);
  a new invitation for the same person revokes the previous one; 409 if the person is already linked to an account; 404 for another tree's person. `GET /admin/invitations` (person, status pending/used/expired/revoked, dates, who used it),
  `DELETE /invitations/{id}` (revoke).
- Public (no login; the token is the access control; rate-limited per address): `GET /invite/{token}` → `{family, person, expires_at}` or 404 (unknown/used/expired/revoked, or the family is paused);
  `POST /invite/{token}/accept` `{email, password, full_name?}` → creates an **active member** account of that tree with `users.member_id` = the invited person, marks the invitation used, signs the person in (cookie). 409 for an e-mail already in use,
  422 for a short password. The role is always `member`.
- Web: page `/moi/[token]` (outside the app shell, like the RSVP card): greets "Bạn được mời vào gia phả <họ> với tư cách <tên>", a small form, then lands on the tree focused on that person. Admin side: a **"Mời người này"** action in the
  person's panel (hidden when the person already has an account) opening a dialog that shows the link once with a copy button (and a select-all fallback for plain HTTP) and the expiry; a **"Lời mời"** section on the Người dùng page lists invitations with "Thu hồi".
- What the link buys the relative: the account shows "Là <tên> trong cây"; the header name opens **"Hồ sơ của tôi"** (the tree focused on their person); after sign-in the tree opens focused on them once per session; the relationship dialog offers a
  one-tap **"Xem với tôi"**. `GET /auth/me` gains `member: {id, name} | null` for this.
- **Admin links themself**: in the person's panel an admin sees **"Đây là tôi"** (PATCH of their own `member_id`, same rule: the person must be in the tree and not linked to another account).

**Removing public sign-up.** Gone: `POST /auth/register`, `GET /auth/bootstrap`, `BOOTSTRAP_CODE`, the `registration` site setting (open/approval/closed) and its UI, `POST /admin/users/approve` + the "Duyệt tất cả" button + the "chờ duyệt" to-do item + the "open registration" notice,
the register rate limit, the `/signup` page and the Signup links. Kept: login, forgot/reset password, `status` values (single approve/disable on the Người dùng page still works for any old `pending` account), `/t/<slug>` (guests of a public tree and the login context),
public trees (read-only for guests). **First superadmin on a fresh install:** `docker compose exec api python scripts/manage.py create-user --role superadmin --email … --name …` (documented in `DOCKER.md`); a signed-in superadmin with no family yet is sent to `/he-thong` instead of an error.
Existing accounts and data are untouched.

## Order and size

1. Phase 1 (small, mostly frontend + two tiny API changes) — one release.
2. Phase 2 (frontend redesign + one migration + `map_links`) — one release.
3. Phase 3 (the editor; the largest, isolated to the chronicles pages) — one release.
4. Phase 4 (invitations + removal of public sign-up) — one release, decided by the owner.
Each phase: spec section → tests first → implement → Playwright on the throwaway stack at phone and desktop widths, in the four themes (contrast/target audit as in the admin console) → docs → merge to local `main` → rebuild the user's stack. Nothing is pushed.

## Left to the builder

File and component names, exact Vietnamese wording, icons (existing inline-SVG style), Tiptap extension set and the Markdown serializer's configuration, thumbnail sizes, the
migration revisions, and the test split.

## Definition of done per phase

Section satisfied; backend + frontend suites green; build and lint clean; Playwright pass (phone + desktop, four themes, no console errors); round-trip tests for the editor; docs and the owner's note updated.
