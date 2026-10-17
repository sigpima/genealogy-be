# Giai đoạn 2 — Hồ sơ đầy đủ, quan hệ phức tạp, công cụ nhập liệu — Design

Date: 2026-10-17
Status: Approved to build by the owner ("tiếp với giai đoạn 2"); the details are my choices (see `../../../../docs/ke-hoach-tinh-nang.md`, mục B1–B3 and decisions D3, D6).

## Why

The imported tree (691 people) has names and generations only. Everything downstream (lịch giỗ, thống kê, tìm kiếm, in phả)
needs real data, and the family has to be able to enter it **fast and in bulk**. This phase adds the missing profile fields,
the relationship fields the real genealogy needs, and the tools to fill 700+ records without opening 700 panels.
All of it is **per tree** (multi-family): every query and import is scoped to the acting tree.

## B1 — Profile fields (members)

| field | meaning |
|---|---|
| `birth_month`, `birth_day`, `death_month`, `death_day` | optional parts of the date; `birth_year`/`death_year` stay as they are |
| `birth_is_lunar` (default false), `death_is_lunar` (default **true**) | the entered month/day are lunar (giỗ is a lunar date) |
| `birth_leap_month`, `death_leap_month` (default false) | the lunar month is a leap month (nhuận) |
| `hometown` | quê quán |
| `phone`, `email` | contact; **hidden from guests** |
| `birth_order` | manual order among siblings (≥1) |

Rules: month 1–12; day 1–31 (1–30 when lunar); **a day needs a month, but month/day do not need a year** (a giỗ only needs
lunar month+day); a leap flag needs a lunar month; a solar date with year+month+day must be a real date; phone is digits and
`+ - ( ) . space`; email must be valid; blanks become NULL; `PUT` stays a full replacement (omitted = default).
Sibling order everywhere (the tree, `sibling_rank`): `birth_order` first (set ones first, ascending), then birth year, then id.

## B3 — Relationships

- `mother_id` (nullable, FK to a member, `ON DELETE SET NULL`): **the mother must be a recorded spouse of the father**
  (`parent_id`) — checked on every write; a mother without a father is refused. The father line stays the tree line (D3).
- `is_adopted` (default false): con nuôi.
- Spouse lists are ordered by marriage year (unknown last), then id.

## B2 — Bulk data tools (admin only, per tree)

- `PATCH /members/{id}`: partial update (only the fields sent), same validation as `PUT`, so a grid can save one cell.
- `GET /members/table`: flat, paged rows for the grid — filters `q` (name), `generation`, `under` (a member id: that
  subtree only), `missing` (`gender|birth_year|hometown|death_year`); spouses are not rows. Each row carries `generation`,
  `parent_name`, `has_children`.
- `GET /members/completeness`: counts for the progress bar (total, with gender, with birth year, with hometown, "basic" =
  gender + birth year).
- `POST /members/{id}/split` `{names: [...]}` (2–50): replaces one member by several siblings (the first name renames the
  original, the rest are new, same parent) — for entries such as "Nguyễn Vô Danh 3 Vị". Refused (409) when the member has
  children or a spouse.
- **CSV**: `GET /members/export.csv` (UTF-8 with BOM for Excel) and `POST /members/import` (multipart `file`,
  `?dry_run=true`). A row with an `id` **updates** that member (it must belong to the tree); a row without `id` **creates** a
  child (needs `full_name` and an existing `parent_id`). **A blank cell means "leave unchanged"; the cell `-` clears the
  value.** All-or-nothing: any error rejects the whole file with a per-row error list (422); `dry_run` validates and
  reports counts without writing. Limits: 5 MB, 10,000 rows. Gender accepts `nam/nữ/khác` or `male/female/other`; flags
  accept `x`, `1`, `true`, `có`.

## Frontend (genealogy-web)

- Panel: shows and edits the new fields (partial dates with a lunar toggle, hometown, phone, email, birth order, mother,
  adoption); a pure helper formats partial dates ("15/08/1945", "12/3 âm lịch", "1945").
- New page `/nhap-lieu` (sidebar "Nhập liệu", admins only): a paged grid with filters (đời, name, a branch via "under",
  "missing X" chips), a completeness bar, inline editing saved per cell through `PATCH`, the "Tách N vị" action,
  CSV export, and CSV import with a dry-run preview before applying.

## Non-goals (later)

Lunar↔solar conversion and giỗ calendar (GĐ5), accent-insensitive/typo-tolerant search (GĐ3), change requests (GĐ4),
undo/audit log, row virtualization (the grid is paged), importing new rows that point at other new rows.
