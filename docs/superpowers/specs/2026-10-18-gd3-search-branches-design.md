# GĐ3 — Search, branches (chi/phái) and basic statistics — Design

Date: 2026-10-18
Status: Approved to build by the owner ("đến giai đoạn 3 đi"); realises roadmap items C + D + "basic statistics" of
`../../../../docs/ke-hoach-tinh-nang.md`. The choices below are mine where the owner did not specify.

## Goals

1. Find a person fast even when typing without diacritics or with old-style tone marks (`hòa` = `hoà` = `hoa`), by name,
   spouse name, hometown, generation, branch, birth years, gender, living/deceased.
2. Let an admin define **branches (chi/phái)**: a branch is the subtree below one person (its head). Show it on the tree
   (colour), on the person's profile, and on a page with per-branch figures.
3. Basic numbers: people per generation, gender, living/deceased, people per branch.

## Design decisions

- **Search runs in Python over the tree's members, not in SQL.** A family has hundreds to a few thousand people (the target
  is 2,000), `/members/table` and the tree already load them all, and this avoids needing the `unaccent`/`pg_trgm`
  extensions (a managed Postgres may not allow `CREATE EXTENSION`). `fold()` = NFD, drop combining marks, `đ→d`, lower-case,
  collapse spaces: the same on both sides, so tone-mark placement cannot matter. Revisit with a SQL index only if a tree grows
  past ~10,000 people.
- **Typo tolerance** ("Có phải bạn muốn tìm…"): only when a text query finds nothing, return up to 5 people whose folded name
  is close (difflib ratio ≥ 0.6, whole name or any single word).
- **A branch = the subtree of its head person.** No per-member assignment, no backfill. A person's branch is the **deepest**
  branch whose head is that person or an ancestor, so a sub-branch overrides its parent branch. A person heads at most one
  branch. Spouses take their partner's branch and generation.
- Branch counts ("con cháu") are the **whole subtree** of the head, sub-branches included, because that is what a family
  means by "chi này có bao nhiêu người"; colours follow the deepest branch.
- Reads (search, branches list, stats) work for guests of a public tree like the tree itself; writes (branches) are admin-only.
  Phone/email are never part of search results.
- `status` uses the same rule as the web app: has a death year → deceased; no birth year → unknown; born ≤ 100 years ago →
  living; else unknown.

## Backend

- `branches(id, tree_id, name, color #rrggbb, description, root_member_id UNIQUE → members ON DELETE CASCADE, created_at)`.
- `GET /branches` (read) → `[{id, name, color, description, root_member_id, root_name, root_generation, member_count}]`,
  ordered by head generation then id. `POST /branches`, `PUT /branches/{id}` (full replacement), `DELETE /branches/{id}`
  (admin). A head from another tree → 404; a person who already heads a branch → 409. Colour defaults to a palette cycle.
- `GET /members/search` (read): `q`, `generation`, `branch` (id; the head's whole subtree), `born_from`, `born_to`,
  `hometown`, `gender` (`male|female|other|unknown`), `status`, `limit` (≤100, default 30), `offset`. Name search needs every
  word of `q` to appear (any order); results rank exact > prefix > word-prefix > contains, then generation, then id; with no
  `q` they come in tree order. Spouses are searched only when `q` is given and report `spouse_of`. Response:
  `{total, items: [{id, full_name, generation, gender, birth_year, death_year, hometown, branch, parent_name, is_spouse,
  spouse_of}], suggestions: [...same item shape...]}`.
- `GET /stats` (read, optional `branch` id): `total`, `by_generation`, `gender`, `status`, `spouses`, `by_branch`,
  `without_branch`.
- `MemberDetail.branch` = the member's deepest branch (`{id, name, color}`) or null.

## Frontend

- The header search folds diacritics too (it stays client-side and instant) and gains a "Tìm nâng cao" link.
- Page `/tim-kiem`: filters + paged results + suggestions; choosing a result opens the tree on that person (`/?focus=<id>`).
- Tree: a thin colour strip on cards of branch members, branch chips under the generation bar (click = fly to the head),
  "Thuộc chi" in the profile panel.
- Page `/chi-phai`: figures (per generation, gender, living/deceased) and one card per branch with its own figures;
  admins create/edit/delete branches (pick the head by searching).

## Non-goals (later)

Per-member manual branch override, a branch's own landing page with a member list, statistics beyond the basics (GĐ8),
accent-insensitive search inside the data-entry grid, a SQL/trigram index.
