# GĐ10 — Export and print: tree images and the "quyển phả" book — Design

Date: 2026-10-19
Status: Approved to build by the owner ("làm liên tục các giai đoạn còn lại"); realises roadmap J1 + J2. Choices below are mine.

## J1 — Tree as an image / PDF (in the browser)

The live tree is an SVG styled by CSS classes and theme variables, which does not survive being saved as an image. So export draws its **own
standalone SVG** with explicit colours (taken from the active theme when you export), from the same tree data:

- scope: the whole tree, one **branch (chi)**, or the descendants of one person; how many generations; with or without years;
- cards show the name, the years and the branch colour; a header line carries the family name and the date;
- PNG: SVG → canvas at up to 2×, **capped so the canvas stays inside browser limits** (a huge tree is scaled down and the dialog warns;
  exporting by branch is the way to get a readable big tree);
- PDF: one page the shape of the picture (a JPEG inside a minimal hand-written PDF), no library.

Years come from the search endpoint (paged), which every reader may call, so no admin-only data is needed.

## J2 — "Quyển phả" (server-side PDF, admins)

`GET /book.pdf` builds a multi-page A4 book with ReportLab and **bundled DejaVu Serif/Sans fonts** (they cover Vietnamese; nothing is read from the
host, so the output is the same in Docker):

1. a cover (family name in a hoành phi-style frame), 2. a table of contents with page numbers,
3. **Tộc ước & gia huấn**, then the other **published** articles, the **bài đệm** and the **timeline** (option `chronicles`),
4. **Phả hệ theo đời**: a section per generation, a block per person — name, parents, dates (lunar death date and giỗ), hometown, spouses and
   marriage years, children, resting place, avatar (option `photos`), and the biography/notes (option `notes`),
5. **Phả đồ**: the tree drawn as vector diagrams on landscape A3 pages, split so every page stays readable — a subtree that is too wide or too
   deep is cut at the bottom and continues on its own page ("▼ xem tiếp").

Contacts (phone, email) are **never** printed unless the admin asks (`contacts=true`); drafts are never printed. The Markdown of articles is
converted to plain paragraphs/lists/quotes. Generation runs in a worker thread; each export is audit-logged (`book.export`).

## Frontend

"Xuất ảnh" in the tree page (dialog with scope/format) and an admin page `/xuat-ban` for the book with its options and a download button.

## Non-goals (later)

Cover image upload, choosing fonts, a printed index of names, page references in the diagrams' "continues" markers, EPUB/Word output,
exporting the PNG of a *theme-less* black-and-white version, a server-side cache of the last book.
