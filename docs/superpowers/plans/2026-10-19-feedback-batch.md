# Feedback batch (header, stepper, data-entry cards, spouse/adoption, media, map link, editor, invitations) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the owner's 8 pieces of feedback in four releases: quick fixes, media + map link, WYSIWYG chronicle editor, invitation links with public sign-up removed.

**Architecture:** Phases 1–2 are mostly frontend redesigns with three tiny API changes (`Completeness`, adoption rule, map-link field). Phase 3 adds a Tiptap editor whose Markdown converter is a pure, tested library, so `articles.body` stays Markdown. Phase 4 adds a `member_invites` table (token hash, one active per person) with a public accept endpoint, then deletes the self-service registration path and everything hanging off it.

**Tech Stack:** FastAPI/SQLAlchemy async/Alembic/pytest (db-test), Next.js 15/React 19/Tailwind v4 tokens, vitest, Tiptap (`@tiptap/react`, `@tiptap/pm`, `@tiptap/starter-kit`, `@tiptap/extension-link`, `@tiptap/extension-image`, `@tiptap/markdown` or a hand-written converter — see Task 9), Playwright on the throwaway stack.

**Spec:** `docs/superpowers/specs/2026-10-19-feedback-batch-design.md` (binding; Phase 4 section reflects the owner's final decisions).

## Global Constraints

- UI: body ≥ 16px (hints ≥ 14px), targets ≥ 44px, visible focus, contrast ≥ 4.5:1 on heritage/warm/modern/elegant, status chips = coloured border + `text-default`, links on page background `text-default` + underline, icon-only buttons have `aria-label`; no hover-only information; no horizontal scroll at 360px.
- Vietnamese UI; pages take no props; `src/lib` imports are relative (vitest has no `@/` alias).
- Articles keep storing Markdown in `articles.body`; the reader (`MarkdownView`), book PDF (`app/core/book.py`) and old articles are not changed.
- Map links: scheme `https` only; hosts `google.com`, `www.google.com`, `maps.google.com`, `maps.app.goo.gl`, `goo.gl` (path starting `/maps`); ≤ 500 chars; anything else 422; opened with `rel="noopener noreferrer"`.
- `burial_map_url` is admin-only (never proposable by members), like the other burial fields.
- Invitation: token shown once, stored as sha256 hash; expires after 14 days; one active invitation per person; role of the created account is always `member`; public endpoints rate-limited per address; unknown/used/expired/revoked/paused-family → the same 404.
- No public registration path remains after Phase 4 (`/auth/register`, `/auth/bootstrap`, `BOOTSTRAP_CODE`, `registration` setting, bulk approve, `/signup`); existing accounts and data stay untouched; single-user PATCH of `status` still works.
- Cross-tree ids → 404; every new write is audited (`audit.record`) in the same transaction.
- Never touch host Postgres (5432) or the developer's `genealogy` DB; tests on `db-test` (`docker compose --profile test up -d --wait db-test`); smoke on the throwaway stack (`up.sh`, `reset.sh`). Do not run `npm run build` while `next dev` runs in the same folder.
- Nothing is pushed; commits as `sigpima <chainpima.work@gmail.com>`, ending with `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`; branch `feat/feedback-batch` in all three repos; per phase `finish.sh` (commit, ff-merge to local `main`, rebuild the compose stack).

## Review Focus

- Generation stepper never hides people: typing 0, 99, empty, "abc", decimals; branch view min > 1; tree with a single generation; a > 2,000-person tree keeps default 4 (Task 3).
- Adoption rule on every write path: create, PUT, PATCH that clears `parent_id`, CSV import, change-request approval; a child under a parent may stay adopted; existing adopted roots still load and can be saved after unticking (Task 1).
- Map link abuse: `javascript:`, `http:`, `https://evil.com/maps`, `https://google.com.evil.com/maps`, userinfo tricks (`https://google.com@evil.com/`), very long URL, whitespace/newlines, uppercase host; coordinates in the link outside ±90/±180 are ignored (Task 6).
- Markdown round-trip: every supported construct, nested lists, adjacent lists, emphasis inside links, `*`/`_`/`[`/`#` typed literally in text, `media:` images, empty document, Windows line endings, unsupported Markdown (html/table/code) survives as text and is never dropped (Task 9).
- Invitation safety: reuse of a used/revoked/expired link, two people racing to accept the same link (exactly one account), e-mail already in use, person linked meanwhile by an admin, paused family, token enumeration (same 404/timing-insensitive compare via hash lookup), accepting never yields a role above `member` (Tasks 11–12).
- Fresh install after signup removal: no user at all, superadmin with zero trees (home must not show a raw error), login page without signup links, old `pending` accounts still approvable one by one (Tasks 13–14).

---

## Phase 1 — quick fixes

### Task 1: Adoption rule and completeness fields (API)

**Files:**
- Create: `app/core/member_rules.py`, `tests/test_adoption_rule.py`, `tests/test_completeness_cards.py`
- Modify: `app/routers/member.py` (create + `_apply_update`), `app/routers/member_tools.py` (`Completeness`, `completeness`, CSV import loop ~line 372), `app/schemas/member.py` (no change to defaults)

**Interfaces:**
- Produces: `def check_adoption(parent_id: int | None, is_adopted: bool) -> None` raising `HTTPException(422, "a person without a father cannot be adopted")` when `is_adopted and parent_id is None`.
- Produces: `Completeness` gains `with_death_year: int` (members with a death year) and `with_avatar: int` (members with `avatar_url`).

- [ ] **Step 1: Failing tests.** `test_adoption_rule.py`: `test_create_root_adopted_is_422`, `test_create_child_adopted_is_ok`, `test_put_adopted_on_root_is_422`, `test_patch_clearing_parent_of_adopted_child_is_422`, `test_csv_import_adopted_without_parent_row_is_rejected_with_row_number`, `test_change_request_making_root_adopted_is_rejected_on_creation_or_approval` (assert 422 at whichever point `_validate` runs, member data unchanged), `test_existing_adopted_root_can_be_saved_after_unticking` (insert the row via session with `is_adopted=True`, `parent_id=None`; PATCH `is_adopted=false` → 200; PATCH an unrelated field while still adopted → 422 is acceptable only if the body re-sends `is_adopted=true`; a PATCH that does not mention `is_adopted` must not be blocked by the stale value). `test_completeness_cards.py`: `test_counts_death_year_and_avatar`, `test_other_trees_not_counted`.
- [ ] **Step 2: Run** `.venv/bin/pytest tests/test_adoption_rule.py tests/test_completeness_cards.py -q` → FAIL.
- [ ] **Step 3: Implement** `check_adoption` and call it with the *final* values: in create, in `_apply_update` only when `is_adopted` or `parent_id` is in `model_fields_set` (final = payload value or current), and per CSV row (failure uses the existing `fail(...)`). Add the two counts to `completeness` with one aggregate query.
- [ ] **Step 4: Run** both files plus `tests/test_member.py tests/test_change_requests.py tests/test_gd2_tools.py` → PASS. **Step 5: Commit** `feat(members): refuse adopted without a father; completeness counts death year and avatar`.

### Task 2: Header redesign (web)

**Files:**
- Modify: `src/components/layout/Header.tsx`, `src/components/layout/ThemeSettingsPopover.tsx` (trigger becomes an icon button with `aria-label="Giao diện"`)
- Create: `src/components/layout/HeaderIconButton.tsx` (shared 44×44 icon button: props `{label: string; onClick?: () => void; href?: string; children: ReactNode}`), `src/lib/auth/roleLabel.ts` + `.test.ts` if role label logic is not already extracted

**Interfaces:**
- Consumes: existing `NotificationsBell`, `TreeSwitcher`, `useSession`/sign-out handler already used by `Header.tsx`.
- Produces: left group = menu button (phone) · family name · user name + role block (≥ md; on phones the name is the `aria-label`/`title` of nothing — shown in the account area of the side menu); right group (`ml-auto`) = `TreeSwitcher`, bell, theme icon, sign-out icon (`aria-label="Đăng xuất"`). Guests: text link "Đăng nhập" only.

- [ ] **Step 1: Write a vitest for the pure part** (`roleLabel`): `admin` → "Quản trị viên", `member` → "Thành viên", `superadmin` → "Quản trị hệ thống" (match the strings `Header.tsx` uses today).
- [ ] **Step 2: Implement** the layout above; no text "Đăng xuất" button remains; every icon has an accessible name and a visible focus ring; tooltips via `title`.
- [ ] **Step 3: Verify** `npm run lint && npx vitest run` green; Playwright (scratchpad `pw/`): header at 360/768/1280 in the four themes — name left of the icons, three icons at the right edge, each ≥ 44px, no overflow, sign-out works, focus order = menu → search → switcher → bell → settings → sign-out.
- [ ] **Step 4: Commit** `feat(web): header with the name on the left and icon actions on the right`.

### Task 3: Generation stepper (web)

**Files:**
- Create: `src/lib/tree/generationStepper.ts`, `src/lib/tree/generationStepper.test.ts`
- Modify: `src/components/tree/GenerationFilterBar.tsx` (rewrite), `src/components/tree/GenealogyTree.tsx` (props, default depth)

**Interfaces:**
- Produces: `clampDepth(raw: string | number, min: number, max: number): number` (non-numeric/empty → `max`; decimals floored; below `min` → `min`; above `max` → `max`); `defaultDepth(max: number, personCount: number): number` (= `max`, but 4 limited to `max` when `personCount > 2000`).
- `GenerationFilterBar` props: `{ min: number; max: number; value: number; onChange: (depth: number) => void; capped?: boolean }`; replaces `{counts, activeDepth, onSelectDepth}`. `min` = displayed root's generation (1 in the whole tree), `max` = youngest generation present in the shown subtree.

- [ ] **Step 1: Failing vitest** for `clampDepth` (`''`→max, `'abc'`→max, `'0'`→min, `'99'`→max, `'3.7'`→3, `5` with min 3 → 5, min=max → that value) and `defaultDepth` (`defaultDepth(7, 100)=7`, `defaultDepth(7, 2500)=4`, `defaultDepth(3, 2500)=3`).
- [ ] **Step 2: Implement** the helpers and the bar: label "Hiển thị đến đời", `−` / `+` buttons (44px, disabled at the bounds with `aria-disabled`), `<input type="number" inputMode="numeric" min max aria-label="Số đời hiển thị">`, caption "trên tổng N đời" (+ " · từ đời K" when `min > 1`, + " · hiển thị bớt cho nhanh" when `capped`). Commit value on blur/Enter via `clampDepth`; ArrowUp/Down step natively. The tree calls `collapsedIdsForDepth(familyTree, depth)` as today; when `displayRoot` changes, re-clamp the value into the new range (keep the user's number if still valid, else `min`/`max`).
- [ ] **Step 3: Verify** vitest; Playwright on a seeded 8-generation tree: opens showing all generations; `−` hides the youngest; typing 3 shows to generation 3; typing 99 snaps to 8; entering a branch view starts the range at the branch's generation; phone width shows one compact row.
- [ ] **Step 4: Commit** `feat(web): generation chips become a number stepper`.

### Task 4: Data-entry cards (web)

**Files:**
- Create: `src/components/data-entry/CompletenessCards.tsx`, `src/lib/data-entry/completenessCards.ts`, `src/lib/data-entry/completenessCards.test.ts`
- Modify: `src/components/data-entry/DataEntry.tsx` (replace the progress bar + text line), `src/lib/data-entry/types.ts` (`with_death_year`, `with_avatar`)

**Interfaces:**
- Produces: `completenessCards(c: Completeness): {field: 'gender'|'birth_year'|'hometown'|'death_year'|'avatar'; label: string; have: number; total: number; percent: number; note?: string}[]` — always five items in that order; labels "đã có giới tính / năm sinh / quê quán / năm mất / ảnh đại diện"; `death_year` note "người còn sống không có năm mất"; `percent` = 0 when `total` is 0.
- `CompletenessCards` props: `{ completeness: Completeness; active: string[]; onToggle: (field: string) => void }`; each card is a `<button aria-pressed>`; grid `grid-cols-2 sm:grid-cols-3` (single column under 360px), 3 + 2 at ≥ sm.

- [ ] **Step 1: Failing vitest** for `completenessCards` (five items, order, `120/810` → `percent 15`, `total 0` → `percent 0`, note only on death_year).
- [ ] **Step 2: Implement** the lib and component; wire `active` to the existing `missing` filter state so a pressed card = the existing "thiếu …" chip active; the chips remain.
- [ ] **Step 3: Verify** Playwright: five cards, numbers match `GET /members/completeness`, pressing "giới tính" filters the table to people without gender, pressing again clears; layout 3+2 on desktop, 2+2+1 at 390px; contrast/targets audit in four themes.
- [ ] **Step 4: Commit** `feat(web): five fixed completeness cards in data entry`.

### Task 5: Spouse and child quick actions; hide "Con nuôi" for the root (web)

**Files:**
- Modify: `src/components/tree/MemberDetailPanel.tsx` (quick actions under the name; "Con nuôi" checkbox ~line 968; tab control ~line 780)
- Create: `src/lib/tree/memberRules.ts` + `.test.ts`

**Interfaces:**
- Produces: `canBeAdopted(member: {parent_id: number | null}): boolean` (= `parent_id !== null`).

- [ ] **Step 1: Failing vitest** for `canBeAdopted` (root false, child true; a member being created as a child of X true).
- [ ] **Step 2: Implement.** Admin-only buttons "＋ Thêm vợ/chồng" and "＋ Thêm con" below the name: they switch to the "Hôn phối & con" tab and focus/scroll to the existing add-spouse form or the add-child form (use refs; open the form if collapsed). The "Con nuôi" checkbox renders only when `canBeAdopted`. Surface the API 422 message if it still occurs.
- [ ] **Step 3: Verify** Playwright: admin sees both buttons on the root and on a child; clicking lands on the right form and focuses its first field; member role sees neither; the root's edit form has no "Con nuôi"; a child's still has it.
- [ ] **Step 4: Phase 1 close-out:** full API suite + `npx vitest run` + `npm run lint` + `npm run build` green; run on the real DB `SELECT count(*) FROM members WHERE is_adopted AND parent_id IS NULL` (read-only) and keep the number for the report; Playwright phone+desktop in four themes + audit; `finish.sh feat/feedback-batch "feat: feedback batch phase 1 - header, generation stepper, data-entry cards, spouse/adoption (docs, bump submodules)"`. Update both `CLAUDE.md` files and `note/tinh-nang-app.md`.

---

## Phase 2 — media area and burial map link

### Task 6: Map-link validation and storage (API)

**Files:**
- Create: `app/core/map_links.py`, `alembic/versions/e7b9c3d61a82_map_links.py` (down_revision `d6a8b2c50f71`; adds `members.burial_map_url VARCHAR(500) NULL`, `places.map_url VARCHAR(500) NULL`), `tests/test_map_links.py`, `tests/test_map_link_fields.py`
- Modify: `app/models/member.py`, `app/models/place.py`, `app/schemas/member.py` (create/update/read/detail), `app/schemas/place.py`, `app/routers/member.py` (`PROFILE_FIELDS`, detail), `app/routers/places.py`, `app/routers/member_tools.py` (CSV columns), `app/core/privacy.py` (treat `burial_map_url` like `burial_*`), proposal field whitelist (where `burial_*` fields are excluded for members)

**Interfaces:**
- Produces: `def clean_map_url(value: str | None) -> str | None` (strip; blank → None; raises `ValueError` when not allowed; used as a pydantic `field_validator` so 422); `def coordinates_from(url: str) -> tuple[float, float] | None` (patterns `@lat,lng`, `!3dLAT!4dLNG`, `?q=lat,lng`, `?ll=lat,lng`, `/maps/place/lat,lng`; out-of-range → None).
- Behaviour: when a saved link yields coordinates, the router sets `burial_latitude/burial_longitude` (member) or `latitude/longitude` (place) from it; when the link is cleared (null) the coordinates are cleared too; a link without coordinates leaves existing coordinates alone.

- [ ] **Step 1: Failing tests** (`test_map_links.py`, pure): accepts `https://www.google.com/maps/place/Hà+Nội/@21.0285,105.8542,15z`, `https://maps.app.goo.gl/AbCd123`, `https://goo.gl/maps/xyz`, `https://maps.google.com/?q=21.03,105.85`; rejects `http://…`, `javascript:alert(1)`, `https://evil.com/maps`, `https://google.com.evil.com/maps`, `https://google.com@evil.com/`, `https://goo.gl/other`, 501 chars, an embedded newline; host match is case-insensitive; `coordinates_from` per pattern incl. negative values, `@95.0,10.0` → None, a link with no numbers → None. `test_map_link_fields.py`: member create/PATCH with a link stores it and fills coordinates; bad link → 422; clearing → coordinates cleared; member (non-admin) proposal containing `burial_map_url` is refused like other burial fields; place create/PATCH likewise; CSV export has the column and import validates it; read endpoints return `burial_map_url`/`map_url`.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement** per the Interfaces (use `urllib.parse.urlsplit` on the stripped value; compare `hostname` lower-cased; reject any `username`/`password` in the netloc; `goo.gl` requires `path.startswith('/maps')`).
- [ ] **Step 4: Run** the two files + `tests/test_places.py tests/test_member_profile*.py tests/test_gd2_*.py tests/test_privacy.py` → PASS. **Step 5: Commit** `feat(api): Google Maps link for burial and places`.

### Task 7: Map-link fields in the forms (web)

**Files:**
- Create: `src/lib/places/mapLink.ts` + `.test.ts`, `src/components/places/MapLinkField.tsx`
- Modify: `src/components/tree/MemberDetailPanel.tsx` (replace "Vĩ độ mộ/Kinh độ mộ" ~lines 977–981), the place form in `src/components/places/` (replace lat/lng inputs), `src/lib/places/*` types and `profileToPayload` (carry `burial_map_url`/`map_url`)

**Interfaces:**
- Produces: `looksLikeMapLink(raw: string): boolean` (client-side hint only; mirrors host list; the API stays the authority); `fallbackMapHref(lat: number | null, lng: number | null): string | null` (`https://www.google.com/maps?q=lat,lng` for old coordinate-only rows).
- `MapLinkField` props `{ value: string; onChange: (v: string) => void; label: string }` — `type="url"`, visible label, helper "Mở Google Maps, bấm Chia sẻ → Sao chép liên kết, dán vào đây", inline error from `looksLikeMapLink`, and a "Mở trên Google Maps" link (`target=_blank rel="noopener noreferrer"`) when valid.

- [ ] **Step 1: Failing vitest** for both helpers (accepted/rejected samples as in Task 6; `fallbackMapHref(null, 1)` → null).
- [ ] **Step 2: Implement.** Read-only panel shows "Xem trên bản đồ" from the link, else from old coordinates via `fallbackMapHref`; the places page keeps its map pins (coordinates still stored).
- [ ] **Step 3: Verify** Playwright: paste a link with `@lat,lng` into a member's burial field → saved, coordinates appear on `/dia-diem`; paste a short link → saved, opens; paste `http://x` → inline error and API 422 shown; old-coordinate person shows "Xem trên bản đồ".
- [ ] **Step 4: Commit** `feat(web): one Google Maps link field instead of coordinates`.

### Task 8: "Tư liệu & bút tích" redesign (web)

**Files:**
- Create: `src/components/media/UploadButton.tsx`, `src/components/media/MediaCard.tsx`, `src/lib/media/uploadQueue.ts` + `.test.ts`, `src/lib/media/groups.ts` + `.test.ts`
- Modify: `src/components/media/MediaGallery.tsx` (rewrite on the new parts; keep its props and the existing viewer), `src/lib/media/*` types if needed

**Interfaces:**
- Produces: `groupMedia(items: MediaItem[]): {photos: MediaItem[]; documents: MediaItem[]}` (photo = `kind==='image'`/image mime; stable order by id); `runUploads(files: File[], upload: (f: File) => Promise<MediaItem>, onProgress: (s: UploadState) => void): Promise<MediaItem[]>` where `UploadState = {done: number; total: number; failed: {name: string; reason: string}[]}`; sequential, a failure does not stop the rest; pre-checks type/size with the same limits `media.py` enforces (read them from the constants in `app/routers/media.py` and mirror).
- `UploadButton` props `{ onFiles: (files: File[]) => void; busy: boolean }`: a primary button "Thêm ảnh hoặc tài liệu" opening a hidden `<input type="file" multiple accept=…>`; drag-and-drop zone ≥ md.

- [ ] **Step 1: Failing vitest**: `groupMedia` (photos vs PDFs, empty), `runUploads` (3 files, middle one rejected → `done 2`, `failed.length 1`, order of progress calls, all rejected → `done 0`).
- [ ] **Step 2: Implement.** Cards: fixed aspect thumbnail, caption below (clamped to 2 lines), ⋯ menu button (44px, admin only) with "Sửa chú thích" / "Xoá" (Xoá via `ConfirmDialog`); documents show a PDF tile with the file name; two groups "Ảnh" and "Tài liệu" with counts; empty state text "Chưa có tư liệu. Ảnh, bản scan gia phả, sắc phong… đều có thể thêm ở đây." (members see no upload and no menu). Status line "Đang tải 2/3…", per-file failures listed with the reason; `aria-live="polite"`.
- [ ] **Step 3: Verify** Playwright: upload 3 files at once (one too big) → 2 cards appear, error row names the big file; no overlap of cards at 360/768/1280; ⋯ menu keyboard-operable (Enter, arrows, Esc); member role sees grid only; four-theme audit.
- [ ] **Step 4: Phase 2 close-out:** full suites, lint, build, migration applied on the real stack at rebuild (check `alembic current`), docs + notes, `finish.sh feat/feedback-batch "feat: feedback batch phase 2 - media area and Google Maps link (docs, bump submodules)"`.

---

## Phase 3 — chronicle editor

### Task 9: Markdown ↔ editor-document converter (web lib)

**Files:**
- Create: `src/lib/chronicles/richText.ts`, `src/lib/chronicles/richText.test.ts`, `src/lib/chronicles/fixtures.ts` (sample bodies), `package.json` deps (Tiptap packages pinned to exact versions, noted in the report)
- Reads: `src/lib/markdown/markdown.ts` (the supported subset), `app/core/book.py` (server-side supported subset)

**Interfaces:**
- Produces: `markdownToDoc(md: string): JSONContent` and `docToMarkdown(doc: JSONContent): string` where `JSONContent` is Tiptap's JSON; supported nodes: paragraph, heading 1–4, bullet/ordered list (nested), blockquote, horizontal rule, hard break; marks: bold, italic, link (`http(s)`/`mailto` only), inline code kept as plain code-styled text; image node `{src: 'media:ID', alt}` ↔ `![alt](media:ID)`. `unsupportedPresent(md: string): boolean` (raw HTML tags, tables, fenced code present).
- Decision for the builder: prefer a **hand-written converter over the repo's own block/inline grammar** (small, no extra dependency, guaranteed same dialect as `markdown.ts` and the PDF); only fall back to an npm Markdown package if the grammar cannot be mapped.

- [ ] **Step 1: Failing tests** (`richText.test.ts`): `docToMarkdown(markdownToDoc(x)) === normalise(x)` for each fixture — headings 1–4, paragraphs, hard breaks, bold/italic/bold-italic, link, link with bold text, image, bullet list, ordered list, nested list, quote with paragraphs, rule, empty string, `\r\n` input; literals typed as text (`2*3*4`, `snake_case`, `[x]`, `# not a heading` escaped when it would become structure); unsupported (`<div>`, table, fenced code) → paragraphs of text, **no characters lost** (assert every non-whitespace character of the input appears in the output), and `unsupportedPresent` true; plus `test_real_article_bodies_round_trip` reading every body from `fixtures.ts` (copy the 3 longest article bodies from the owner's real data via `docker compose exec db psql -c "select body from articles"` into the fixture file — they contain no secrets, are family chronicles; if the owner prefers not, use synthetic ones of the same shape).
- [ ] **Step 2: Run** `npx vitest run src/lib/chronicles/richText.test.ts` → FAIL. **Step 3: Implement** the two functions (block parser line-based, inline tokenizer with escape handling; serializer escapes only what would change meaning on re-parse).
- [ ] **Step 4: Run** → PASS; also run existing `src/lib/markdown` tests. **Step 5: Commit** `feat(web): lossless Markdown <-> rich text converter for chronicles`.

### Task 10: WYSIWYG editor, toolbar and page integration (web)

**Files:**
- Create: `src/components/chronicles/RichTextEditor.tsx` (client, default export), `src/components/chronicles/EditorToolbar.tsx`, `src/components/chronicles/LinkDialog.tsx`, `src/components/chronicles/ImagePickerDialog.tsx`, `src/lib/chronicles/linkInput.ts` + `.test.ts`
- Modify: `src/components/chronicles/ArticleEditor.tsx` (swap textarea for the lazily imported editor via `next/dynamic` with `ssr:false` and a skeleton; keep title/cover/pinned/mentions/draft controls and the "Xem trước" toggle), `src/app/globals.css` (editor content typography reuses the reader's prose classes)

**Interfaces:**
- Consumes: `markdownToDoc`, `docToMarkdown`, `unsupportedPresent` (Task 9).
- Produces: `RichTextEditor` props `{ value: string /* Markdown */; onChange: (markdown: string) => void; photos: {id: number; url: string; caption: string}[]; onNotice?: (message: string) => void }`; `normaliseLinkInput(raw: string): string | null` (adds `https://` to bare domains; accepts `http(s)://`, `mailto:`; rejects `javascript:`/`data:`).
- Toolbar (sticky, wraps on phones, all `aria-label` + `aria-pressed` where toggles, 44px): Hoàn tác, Làm lại | Tiêu đề lớn (H2), Tiêu đề nhỏ (H3), Đoạn văn | In đậm, In nghiêng | Danh sách chấm, Danh sách số | Trích dẫn | Đường kẻ | Chèn link | Chèn ảnh. Active states follow the selection; shortcuts Ctrl/Cmd+B/I/K work; no Markdown is ever displayed.

- [ ] **Step 1: Failing vitest** for `normaliseLinkInput` (`'example.com'`→`'https://example.com'`, `'javascript:alert(1)'`→null, `'mailto:a@b.c'` ok, `''`→null, spaces trimmed).
- [ ] **Step 2: Implement** the editor on StarterKit (heading levels 2–3 only exposed; levels 1 and 4 render if present in old text), Link, Image (custom attrs for `media:ID`; the picker lists the article's uploaded photos exactly as today's textarea flow does); `onChange` emits `docToMarkdown` debounced ≤ 300ms and on blur; opening an article whose body `unsupportedPresent` → `onNotice("Một số định dạng cũ được hiển thị như văn bản thường")` once. Unsaved-changes guard stays as in `ArticleEditor`.
- [ ] **Step 3: Verify** Playwright (desktop + 390px): open an existing real article → text identical in the reader after "Lưu" without edits (compare the `body` column before/after through the API: byte-equal after the converter's normalisation); select a word → Đậm → saved Markdown has `**word**`; make a bullet list, a heading, a quote; add a link via dialog; insert a photo; undo/redo; keyboard-only path; toolbar buttons report `aria-pressed`; book PDF export still renders the new article; four-theme audit; check the editor chunk is not in the first-load bundle of other pages (`npm run build` size table before/after, record both numbers).
- [ ] **Step 4: Phase 3 close-out:** suites, lint, build, docs + notes (dependency list and size), `finish.sh feat/feedback-batch "feat: feedback batch phase 3 - WYSIWYG chronicle editor (docs, bump submodules)"`.

---

## Phase 4 — invitation links, public sign-up removed

### Task 11: Invitations — model and admin endpoints (API)

**Files:**
- Create: `alembic/versions/f8c0d4e72b93_member_invites.py` (down_revision = Task 6's revision), `app/models/member_invite.py`, `app/schemas/member_invite.py`, `app/routers/member_invites.py`, `tests/test_member_invites_admin.py`
- Modify: `app/main.py`, `alembic/env.py` (import model), `app/core/audit_kinds.py` (`invite.create`, `invite.revoke` → kind "users"), `app/core/tree_removal.py` (delete the tree's invites; CASCADE from members already covers rows), tests' `TRUNCATE` list in `conftest.py` if it names tables

**Interfaces:**
- Produces: table `member_invites(id PK, tree_id FK trees CASCADE, member_id FK members CASCADE, token_hash VARCHAR(64) UNIQUE NOT NULL, created_by INT NULL FK users SET NULL, created_at, expires_at, used_at NULL, used_by INT NULL FK users SET NULL, revoked_at NULL)`; model `MemberInvite`. Named `member_invites` because `invitations`/`event_cards` already mean RSVP cards.
- Produces: `POST /members/{id}/invitation` (admin) → `201 {id, path: "/moi/<token>", expires_at}`; `GET /admin/invitations` → `[{id, member: PersonRef, status: 'pending'|'used'|'expired'|'revoked', created_at, expires_at, used_at, used_by_email}]`; `DELETE /invitations/{id}` → 204 (revokes; idempotent on already-revoked; 404 other tree). `def invite_status(invite: MemberInvite, now: datetime) -> str` in `app/core/invites.py` (shared with Task 12), `hash_token(token: str) -> str` (sha256 hex) — reuse the reset-token helper style from `routers/auth.py::_hash_reset_token`.

- [ ] **Step 1: Failing tests:** admin creates → response has a token path, DB stores only the hash (`token not in` any column); second create for same person revokes the first (status `revoked`); person already linked to a user → 409; other tree's person → 404; member role 403; guest 401; `GET /admin/invitations` lists with right statuses (pending/expired via backdated `expires_at`/revoked) and other trees' invites absent; revoke 204 then status `revoked`; audit rows `invite.create` / `invite.revoke` exist without the token; a deleted person removes its invites.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement** (`secrets.token_urlsafe(32)`, 14-day expiry, revoke previous in the same transaction, `audit.record`). **Step 4: Run** the file + `tests/test_tree_delete.py tests/test_audit.py` → PASS. **Step 5: Commit** `feat(api): per-person invitation links (admin side)`.

### Task 12: Invitations — public accept, `/auth/me` member, self-link rule (API)

**Files:**
- Create: `app/routers/invite_public.py` (prefix `/invite`), `tests/test_member_invites_public.py`, `tests/test_auth_me_member.py`
- Modify: `app/main.py`, `app/core/rate_limit.py` usage (new limiter key `invite` per IP, same style as login), `app/schemas/auth.py` or `user.py` (`UserRead.member: PersonRef | None`), `app/routers/auth.py::read_current_user` (fill `member`), `app/routers/admin.py` PATCH path (already validates `member_id`; add a test that an **admin may PATCH their own `member_id`** and a member may not)

**Interfaces:**
- Consumes: `invite_status`, `hash_token` (Task 11); `core.tenancy.is_paused`.
- Produces: `GET /invite/{token}` → `{family: str, person: str, expires_at: datetime}` or 404; `POST /invite/{token}/accept` body `{email: EmailStr, password: str (min 8), full_name: str | None}` → 201 `UserRead` + sets the auth cookie exactly as login does; 409 `email already registered`; 422 short password; 404 for any non-pending invite or paused family; race-safe (`UPDATE … SET used_at … WHERE id=:id AND used_at IS NULL AND revoked_at IS NULL RETURNING` — zero rows → 404).
- `UserRead.member`: `{id, name} | null` from `users.member_id`.

- [ ] **Step 1: Failing tests:** `test_view_returns_family_and_person_only` (no ids/emails of others); `test_accept_creates_active_member_linked_and_signed_in` (role `member`, status `active`, `tree_id`, `member_id`, cookie works on `/auth/me` which shows `member`); `test_used_link_cannot_be_reused`; `test_revoked_expired_unknown_all_404_same_body`; `test_email_in_use_409_and_invite_stays_usable`; `test_concurrent_accepts_make_one_account` (two `asyncio.gather` posts with different emails → one 201, one 404, one user row); `test_person_linked_meanwhile_by_admin_404_or_409` (choose 409 and document); `test_paused_family_404`; `test_rate_limited` (with the limiter enabled for this test only, per `test_rate_limit.py` pattern); `test_admin_can_link_self_and_member_cannot`; `/auth/me` returns `member: null` for unlinked users.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** the new files + `tests/test_auth.py tests/test_admin_users.py` (those may still use register until Task 13) → PASS. **Step 5: Commit** `feat(api): accept an invitation, /auth/me shows the linked person`.

### Task 13: Remove self-service registration (API) and rewrite its tests

**Files:**
- Modify: `app/routers/auth.py` (delete `register`, `bootstrap_state`, bootstrap/registration helpers, register limiter and `BOOTSTRAP_CODE` use), `app/core/config.py` (drop `bootstrap_code`), `app/core/roles.py` (drop `registration` from `SETTINGS`), `app/schemas/admin.py` (`SiteInfo`, `SiteSettingsPayload` lose `registration`; drop `BulkApproved`), `app/schemas/user.py` (drop bootstrap field), `app/core/admin_overview.py` (drop `pending_users` item/count and `open_registration` notice — keep the `pending` status handling elsewhere), `app/routers/admin.py` (drop `POST /users/approve`), `app/routers/site.py` if it exposes the setting, `docker-compose.yml`/`.env.example` (root repo: drop `BOOTSTRAP_CODE`), `scripts/manage.py` (check `create-user --role superadmin` exists and works on an empty DB; add a test if missing)
- Delete: `tests/test_bootstrap_code.py`
- Modify tests: `tests/test_auth.py` (9), `tests/test_password_reset.py` (5), `tests/test_roles_auth.py`, `tests/test_rate_limit.py`, `tests/test_member.py`, `tests/test_marriage.py`, `tests/test_avatar.py`, `tests/test_config.py`, `tests/test_admin_overview.py`, `tests/test_admin_users.py`, `tests/test_roles_admin.py` (wherever `registration`/`approve`/`pending_users` appear)
- Create: `tests/test_registration_removed.py`

**Interfaces:**
- Consumes: existing helpers `create_user`, `create_tree` (see their current signatures in the test modules/`app/core` used by `manage.py`) and `make_client` from `tests/conftest.py`. Add to `conftest.py` one helper `async def login_as(client, email, password) -> None` only if the existing ones lack a way to sign in via `/auth/login`.

- [ ] **Step 1: Failing tests** (`test_registration_removed.py`): `POST /auth/register` → 404/405; `GET /auth/bootstrap` → 404; `GET /site` (whatever the public site-info route is) has no `registration`; `PUT` settings with a `registration` key is ignored or 422 (choose: extra keys → 422 per the existing payload model config; assert what actually happens and keep it); `POST /admin/users/approve` → 404/405; admin overview has no `pending_users` / `open_registration`; single-user PATCH `status: active` of a `pending` user still works and a `pending` user still cannot log in (existing behaviour kept); `manage.py create-user --role superadmin` creates a user who can log in on an empty DB.
- [ ] **Step 2: Run** → FAIL. **Step 3: Delete** the code listed; rewrite each former register call in the listed tests to create the user via the helpers (admin/member as the test needs) and log in through `/auth/login` where the test is about login/session behaviour; keep test names and intent; delete assertions that only exercised registration modes (replace with the new test file above).
- [ ] **Step 4: Run the whole API suite** `.venv/bin/pytest -q` → all green (record count). **Step 5: Commit** `feat(api)!: remove public sign-up, bootstrap code and registration setting`.

### Task 14: Remove sign-up (web) and fresh-install redirect

**Files:**
- Delete: `src/app/signup/` (page + components), `src/lib/auth/bootstrap.ts` and its test
- Modify: `src/app/login/` (remove Signup links; keep forgot-password), `src/lib/auth/session.ts` (`SiteInfo` without `registration`), `src/lib/tree.ts`/`src/lib/admin/users.ts` (types: drop `registration`, `approveAll`), `src/components/admin/SettingsPanel.tsx` (remove the registration block), `src/components/admin/UsersView.tsx` ("Duyệt tất cả" button), `src/lib/admin/home*` (to-do item key `pending_users`, notice `open_registration`), `src/app/page.tsx` and the tree page loader (superadmin with no trees → `router.replace('/he-thong')`), any `/t/<slug>` page text that offers sign-up
- Create: `src/lib/auth/landing.ts` + `.test.ts`

**Interfaces:**
- Produces: `landingPath(user: {role: string} | null, treeCount: number | null): '/' | '/he-thong' | '/login'` (`superadmin` with `treeCount === 0` → `/he-thong`; no user → `/login`; otherwise `/`).

- [ ] **Step 1: Failing vitest** for `landingPath` (the three cases + `treeCount` null → `/`). **Step 2: Implement** the deletions/edits; `grep -rn "signup\|register\|bootstrap\|registration" src` must return only unrelated hits (document any left). Home loader calls `landingPath` when the API returns "no tree yet".
- [ ] **Step 3: Verify** `npx tsc --noEmit`, lint, vitest; Playwright on an **empty** throwaway DB: create the superadmin by CLI, log in → lands on `/he-thong` (no error page); the login page has no signup link; `/signup` → 404; admin Settings page has no registration block; Users page still lists a seeded `pending` user with its single "Duyệt".
- [ ] **Step 4: Commit** `feat(web): remove sign-up pages and registration settings; superadmin without a family lands on the console`.

### Task 15: Invite page, admin invite UI, "Hồ sơ của tôi" (web)

**Files:**
- Create: `src/app/moi/[token]/page.tsx` (+ `components/InviteForm.tsx`), `src/lib/invites/invites.ts` + `.test.ts`, `src/components/admin/InvitationsPanel.tsx`, `src/components/tree/InviteDialog.tsx`
- Modify: `src/components/layout/AppShell.tsx` (route `/moi/*` renders without the shell, like `/thiep/*`), `src/components/tree/MemberDetailPanel.tsx` ("Mời người này", "Đây là tôi", hidden when the person has an account / is the admin's own person), `src/components/admin/UsersView.tsx` or `src/app/admin/nguoi-dung/page.tsx` (render `InvitationsPanel`), `src/components/layout/Header.tsx` (user name links to "Hồ sơ của tôi" when `member` is set), `src/lib/auth/session.ts` (`member` on the session user), `src/components/tree/GenealogyTree.tsx` (`?focus=<id>`; focus "tôi" once per browser session via `sessionStorage`, guarded by try/catch), `src/components/tree/RelationshipDialog.tsx` ("Xem với tôi" quick pick)

**Interfaces:**
- Produces: `inviteUrl(path: string, origin: string): string`; `inviteStatusLabel(status: 'pending'|'used'|'expired'|'revoked'): string` ("Đang chờ", "Đã dùng", "Hết hạn", "Đã thu hồi"); API wrappers `createInvitation(memberId)`, `listInvitations()`, `revokeInvitation(id)`, `getInvite(token)`, `acceptInvite(token, body)`.
- Consumes: Task 11/12 endpoints; `useDialogFocus`, `ConfirmDialog`.

- [ ] **Step 1: Failing vitest** for `inviteUrl`, `inviteStatusLabel`, and the focus-once helper (`shouldFocusMe(storage, memberId)` returns true once per stored key, false after; storage throwing → false).
- [ ] **Step 2: Implement.** `/moi/[token]`: loads `getInvite`; 404 → friendly "Lời mời không còn hiệu lực. Hãy nhờ người quản trị gửi lại."; otherwise greeting "Bạn được mời vào gia phả {family} với tư cách {person}", fields e-mail / mật khẩu (visible labels, hint ≥ 8 ký tự) / họ tên optional, on success `router.replace('/?focus=<member_id>')`. `InviteDialog`: shows the link once (readonly input auto-selected, "Sao chép" button with a select-all fallback when `navigator.clipboard` is missing), expiry date, note that a new link cancels the old one. `InvitationsPanel`: cards on phone / table on desktop, status chip, "Thu hồi" with `ConfirmDialog`. "Đây là tôi" PATCHes own `member_id` through the existing admin users endpoint and refreshes the session.
- [ ] **Step 3: Verify** Playwright end-to-end on the throwaway stack: admin opens a person → "Mời người này" → copies link → new private browser context opens it → registers → lands on the tree focused on that person, header shows the name linking to "Hồ sơ của tôi"; the same link again → friendly message; admin sees status "Đã dùng"; revoke flow; admin presses "Đây là tôi" on own person and the header link appears; "Xem với tôi" in the relationship dialog pre-fills the person; phone + desktop, four-theme audit; no console errors.
- [ ] **Step 4: Commit** `feat(web): invitation page, admin invite tools and my-profile links`.

### Task 16: Docs, notes, whole-branch gate

**Files:**
- Modify: `DOCKER.md` (runbook: first superadmin by CLI, creating a family and first admin, inviting relatives; remove BOOTSTRAP_CODE text), root `README`/docs roadmap, `genealogy-api/CLAUDE.md`, `genealogy-web/CLAUDE.md`, `note/tinh-nang-app.md`, new `note/19.10-gop-y-va-moi-thanh-vien.md` (what changed, leftovers, adopted-roots count from Task 5, bundle size numbers)

- [ ] **Step 1:** Update docs as listed; state clearly that public sign-up no longer exists and how an owner recovers (CLI `create-user`, `set-password`).
- [ ] **Step 2: Full gate:** API `.venv/bin/pytest -q`, web `npx vitest run && npm run lint && npm run build`, Playwright regression of earlier suites (admin console, platform console, tree, chronicles, data-entry) on the throwaway stack.
- [ ] **Step 3:** Dispatch one fresh reviewer (most capable model) on `git diff main...feat/feedback-batch` in all three repos with the Review Focus list; fix confirmed findings RED→GREEN, re-run the gate.
- [ ] **Step 4:** `finish.sh feat/feedback-batch "feat: feedback batch phase 4 - invitation links, no public sign-up (docs, bump submodules)"`; verify on the user's compose stack: `alembic current` is the latest revision, the login page has no signup link, `/signup` 404, an invitation round trip works; final report in Vietnamese with leftovers.

## Self-review notes

- Spec coverage: item 1 → Tasks 9–10; 2 → 3; 3 → 11–15; 4 → 2; 5 → 8; 6 → 1, 5; 7 → 1, 4; 8 → 6–7; removal list → 13–14; docs/runbook → 16.
- Names used across tasks: `check_adoption`, `Completeness.with_death_year/with_avatar`, `clean_map_url`, `coordinates_from`, `MemberInvite`/`member_invites`, `invite_status`, `hash_token`, `landingPath`, `markdownToDoc`/`docToMarkdown` — each defined once in its producing task.
- Migration chain: `d6a8b2c50f71` → `e7b9c3d61a82` (Task 6) → `f8c0d4e72b93` (Task 11).
