# Multi-family (multi-tree) — Design

Date: 2026-10-17
Status: Approved to build by the owner ("làm nhiều gia đình luôn"); the details below are my choices for what the owner did not specify.
Supersedes decision D1 of `../../../../docs/ke-hoach-tinh-nang.md` (it was "one tree per deployment").

## Goal

One deployment hosts **many families**. Each family has its **own tree** (its own members, settings, users) and
its own **admin**. The owner of the platform is the **superadmin**. Right now only the tree-admin side is built:
the superadmin **management page is deferred**, so trees and tree admins are created with a command-line tool.

## Roles

| role | belongs to | can |
|---|---|---|
| `superadmin` | no tree (`users.tree_id` NULL) | everything, in **any** tree; creates trees/admins (CLI for now) |
| `admin` | exactly one tree | everything inside **their** tree: edit members, approve/create users, tree settings |
| `member` | exactly one tree | read their tree |
| guest | – | read a tree only if that tree is `public` (redacted detail) |

- A tree admin can only assign `admin`/`member`. `superadmin` is granted only from the CLI, and tree admins can
  neither see nor modify superadmins.
- A user belongs to **one** tree. Email stays globally unique, so login needs no tree.

## Data model

- `trees(id, name, slug UNIQUE, created_at)`.
- `members.tree_id` NOT NULL (FK, indexed). Spouses are members too, so they carry the same `tree_id`;
  `marriages` need no column (both rows are in one tree).
- `users.tree_id` nullable (NULL only for superadmins).
- `site_settings` becomes **per tree**: primary key `(tree_id, key)`; visibility and registration mode are per tree.
- Migration: if data already exists, it all moves into one default tree (`slug = "default"`); existing users
  stay `admin` of it. Roles are changed afterwards with the CLI (the owner becomes `superadmin`).

## Which tree does a request act on?

1. **Signed-in user:** their own `tree_id`. A **superadmin** picks the tree with the `X-Tree-Id` header; without it
   they get the lowest-id tree (so the existing UI keeps working until the management page exists).
2. **Guest / signup:** the `tree_slug` **cookie**, set by visiting `/t/<slug>` (a small Next route that sets the
   cookie and redirects to `/`). If there is **exactly one** tree, it is used without any cookie (so a single-family
   install behaves as before). With several trees and no cookie, signup answers 400 and reads answer 404.
3. A tree is **never** inferred for a signed-in non-superadmin from a header or cookie: no way to peek at another tree.

Cross-tree access always answers **404** (not 403), so ids of other trees cannot be probed.

## Behaviour changes

- `register`: the first user ever becomes `superadmin` (tree NULL) and a default tree is created if none exists
  (a fresh install stays usable). Later users join the resolved tree as `member`, `pending`/`active`/refused by
  **that tree's** registration setting.
- Everything under `/members` is filtered by the acting tree; creating a member sets `tree_id`; parents, spouses
  and marriages must belong to the same tree.
- `/admin/users`, `/admin/settings`, `/site/info` act on the resolved tree. The last-admin guard is per tree.
- `GET /auth/me` also returns `tree_id`, `tree_name`.

## CLI (`scripts/manage.py`) — stands in for the superadmin page

`create-tree`, `rename-tree`, `create-user` (any role, optional generated password), `set-role`, `list`.
`seed_members.py` gains `--tree-slug`.

## Non-goals (later)

Superadmin web UI, tree-switcher in the UI, subdomain routing, moving a user between trees, deleting a tree,
per-tree branding.
