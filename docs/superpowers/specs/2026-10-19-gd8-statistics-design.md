# GĐ8 — Full statistics and data completeness — Design

Date: 2026-10-19
Status: Approved to build by the owner ("làm liên tục các giai đoạn còn lại"); realises roadmap I. Choices below are mine.

## Goal

A dashboard of the family in numbers — and, more usefully, a **completeness board** that turns the gaps ("how many people have no
birth year?") into links that take an admin straight to the people to fix.

## What is computed (`GET /stats/overview`, readable like the tree)

All of it from the tree loaded in memory (as search and the data-entry table do), over **blood members** (spouses are counted once, separately):

- totals: members, spouses, generations, living / deceased / unknown (the same living rule as everywhere);
- gender overall and per generation; people per generation and per branch;
- **lifespan** (deceased with both years, 0–120 years to ignore typos): count, average, median, shortest, longest, average by gender;
- **birth decades**;
- **children**: parents, average children per parent, childless people, the person with most children;
- **longest line**: how many generations deep and the chain of names from the root to the deepest descendant;
- **common middle names (chữ đệm) and given names**: the word after the surname for names of 3+ words, the last word; top 10, accents folded when counting;
- **completeness** per field (gender, birth year, birth day+month, hometown, residence, avatar, any photo) as `have / total`.

Aggregates only: guests of a public tree get them too (no names beyond the person with most children and the longest line, which
are in the public tree anyway).

## Turning numbers into work

- `/members/table?missing=avatar` joins the existing missing filters (gender, birth_year, hometown, death_year).
- The page links every completeness row to the data-entry grid pre-filtered (`/nhap-lieu?missing=…`, admins) and every bar to the
  search page pre-filtered (`/tim-kiem?generation=3`, `?gender=female`, `?status=living`, `?born_from=1950&born_to=1959`,
  `?branch=ID`). The search and data-entry pages read those parameters.

## Frontend

`/thong-ke` (sidebar "Thống kê"): key-number cards, bar charts built from accessible links with their numbers written out (no chart
library, high contrast, readable in all themes), the completeness board, the longest line, common names. `/chi-phai` keeps its own
branch figures.

## Non-goals (later)

Charts over time, comparing branches side by side, exporting the figures, a per-person "health" score.
