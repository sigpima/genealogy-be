# GĐ11 — Relationships, privacy per field, view options, safe operations — Design

Date: 2026-10-19
Status: Approved to build by the owner ("làm liên tục các giai đoạn còn lại"); realises roadmap B4 + B5 + L. The choices below
are mine where the owner did not specify.

## 1. Privacy per field

- Fields an admin can place: `phone`, `email`, `residence`, `notes`, `burial` (resting place link, plot, free-text place,
  GPS), `avatar`, `hometown`. Level of each: `admin` (admins only), `member` (any signed-in member of the tree), `public`
  (also guests of a *public* tree). **Defaults keep today's behaviour**: everything `member` except `hometown` and `avatar` = `public` (a public tree already showed both to guests).
- Stored as `site_settings` rows `privacy.<field>` (no migration). `GET /admin/privacy` → `{fields: {field: level}}`;
  `PUT /admin/privacy` merges the given fields (unknown field/level → 422); audited as `privacy.update` with `{field: [old, new]}`.
- One redaction layer, `app/core/privacy.py`: `viewer_rank` (guest 0, member 1, admin/superadmin 2) and `Privacy.can_see(field)`.
  Applied to: the member detail (fields **and the spouses' notes**), the avatar *file* (404 unless the viewer may see avatars),
  change requests (a member cannot propose a field they cannot see — 422; `old/base` of a hidden field are dropped when a
  non-admin reads a request). Admins always see everything. Birth/death years, names, gender and the tree shape are not
  configurable (they are the tree).

## 2. Kinship calculator (B4)

`GET /members/relationship?a=&b=` (read; both ids must be in the tree) → who A is to B and B to A in Vietnamese terms.
Pure function in `app/core/kinship.py` over the parent chain (`parent_id` = father line):

- same person; spouse (`vợ`/`chồng`); parent/child (`cha/mẹ`, `con`); ancestors by distance (`ông/bà`, `cụ`, `kỵ`, then "tổ cách N đời");
  descendants (`cháu`, `chắt`, `chút`, then "cháu cách N đời");
- siblings `anh/chị/em` ordered by `birth_order`, else birth year; uncles/aunts of the father's line: **older than the father → `bác`**,
  younger → `chú` (male) / `cô` (female), with `ông`/`cụ` prefixes for higher generations and `họ` when the common ancestor
  is more than one step above the older one; cousins `anh/chị/em họ` ordered **by the order of their branches, not by age**;
- the child's mother (`mother_id`) is `mẹ`; a spouse of a relative is reported as "vợ/chồng của <relative>" plus that
  relative's relation (no special in-law terms); people in different trees / no common ancestor → `none`.
- Response: `{kind, a_is, b_is, sentence, common_ancestor, steps_a, steps_b}` (`a_is` = what A is to B). Maternal relatives
  (`cậu`, `dì`, ...) are not in the tree (the mother is a spouse, not a parent) and cannot be derived.

## 3. View options (B5)

Frontend only: a toggle **horizontal / vertical** layout of the tree (the choice remembered in `localStorage`), and
"Xem riêng nhánh này" in the profile panel (descendants of one person, like the ancestor view that already exists).

## 4. Operations

- **Rate limiting** (in memory, per process — a single API worker is what compose runs; Redis would be needed for several):
  login 20 / 5 min per IP and 8 / 5 min per account, register 10 / hour per IP, forgot-password 5 / hour per IP, public
  RSVP 40 / 10 min per IP; only login *failures* count against an account. 429 with `Retry-After`. The client IP is read from `X-Forwarded-For` only as many hops
  from the right as `TRUSTED_PROXY_HOPS` says (default 0 = trust nothing). **Measured, not assumed:** Next.js's `/api` proxy does not add the
  visitor's address, so without a real reverse proxy in front every request reaches the API from the web container; the per-IP limits then
  count everybody together and are loosened ×5 so the family is not throttled, while the per-account failure limit does the real work.
  Behind nginx (which must set `X-Forwarded-For`) set `TRUSTED_PROXY_HOPS=1`. `RATE_LIMIT_ENABLED=false` turns it off (tests).
- **Security headers**: the API adds `X-Content-Type-Options`, `Referrer-Policy`, `X-Frame-Options`; the web adds the same plus
  `Permissions-Policy` and (production only) a Content-Security-Policy that allows the map tiles, `blob:`/`data:` images for the export.
  HSTS is the reverse proxy's job (documented in DOCKER.md), because sending it over plain HTTP is wrong.
- **Backup**: `scripts/backup.sh` (Postgres dump + the uploads volume, timestamped folder, keeps the newest N) and
  `scripts/restore.sh` (restores into a *named* database, refusing the live one without `--force-live`), `docs/SAO-LUU.md` with the
  cron line and the rehearsal that was actually run.
- **Full data export**: `GET /export/data.json` (admin, audited as `data.export`): every table of the tree (members, marriages,
  branches, places, media metadata, articles incl. drafts, timeline, generation words, events, event cards), **never password
  hashes, tokens or other trees' data**; the page `/xuat-ban` links it. Files are covered by the backup.

## Non-goals (later)

Maternal kinship terms and in-law terms, per-item privacy for media, Redis-backed rate limiting, 2FA, a restore button in the UI.
