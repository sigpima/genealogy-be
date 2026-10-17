# GĐ7 — Chronicles (sử ký): articles, timeline, generation words — Design

Date: 2026-10-19
Status: Approved to build by the owner ("làm liên tục các giai đoạn còn lại"); realises roadmap H. Choices below are mine.

## Goal

A home for the family's written memory: where the clan came from, the rules it lives by (tộc ước / gia huấn), stories of
notable people, a timeline, and the **bài đệm / tự bối** (the poem that fixes the middle name of each generation).

## Articles

`articles(tree_id, title, slug, kind origin|lineage|precepts|event|person|other, body Markdown, status draft|published, pinned,
position, cover_media_id)` + `article_members` (the people an article mentions, chosen by the admin — nothing is parsed out of
the text). Admins write; **members and guests read published articles** (guests only on a public tree; drafts are for admins).

- The slug comes from the title (diacritics folded) and is unique per tree (`-2`, `-3`… on a clash); it is stable once created.
- Order: pinned first, then `position`, then newest. `POST /articles/reorder` sets positions.
- Photos are media attached to the article (`media.article_id`, admin upload, signed-in viewers only — the GĐ6 rule). In the
  body, `![caption](media:ID)` shows an attached image **to signed-in readers**; a guest sees the caption text instead.
- A person's profile lists the published articles that mention them ("Được nhắc trong…").
- Markdown is rendered by a small in-house renderer that builds React elements (headings, emphasis, lists, quotes, rules, links
  to http/https/mailto, `media:` images). No raw HTML is ever interpreted, so there is nothing to sanitise.

## Timeline

`timeline_entries(year, month?, day?, title, body?, member_id?, article_id?)`: the clan's own history (a migration, a flood, the
building of the nhà thờ). Sorted by date. Admin writes; readers as for articles.

## Bài đệm (generation words)

`generation_words(tree_id, generation, word, meaning?)`, replaced as a whole by `PUT /generation-poem` (admin). The panel shows the
word of the next generation when an admin adds a child ("Chữ đệm đời 5: Văn") and the chronicles page lists them.

## Navigation

The sidebar becomes a drawer on phones (menu button in the header); a new "Sử ký" item.

## Non-goals (later)

WYSIWYG editing, article revisions, comments, per-article privacy, parsing mentions from the text, inline photo galleries, tables
in Markdown.
