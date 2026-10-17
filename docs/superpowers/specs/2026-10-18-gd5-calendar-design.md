# GĐ5 — Lunar calendar, giỗ, events, .ics and reminders — Design

Date: 2026-10-18
Status: Approved to build by the owner ("tiếp tục giai đoạn 5"); realises roadmap F1–F3 (F4, invitation cards, is GĐ9).
The choices below are mine where the owner did not specify.

## Goal

The thing a family tree is for in practice: **never miss a giỗ**. Show the lunar and solar date side by side, list the death
anniversaries computed from the data already entered (GĐ2), let admins add family events, give each person a phone-calendar
link, and remind people by email and in the web before the day.

## Lunar calendar

`app/core/lunar.py`: Hồ Ngọc Đức's astronomical algorithm with the **UTC+7 meridian** (the Chinese calendar uses UTC+8 and
disagrees in a few years), no lookup table. Tested against Tết 1975–2027, Trung thu, Giỗ Tổ, known leap months and a full
round trip of every day for 50 years.

## Giỗ (death anniversaries) — computed, never stored

For each person with a death **month and day**:

- `death_is_lunar` → that lunar date. Solar with a full date (year+month+day) → converted once to the lunar date. Solar without a
  year cannot be converted (the lunar date changes every year) → not computable; the calendar reports how many people are skipped.
- Every lunar year **after** the death year gets an anniversary: `years` = lunar year − death year ("giỗ lần thứ N"; N = 1 is the
  giỗ đầu). With no death year the giỗ recurs every year without a number.
- Death in a **leap month** → the giỗ is held in the regular month of that number every year (common custom); a day 30 in a month
  of 29 days falls on day 29.
- Spouses count like everybody else.

## Events

`events(tree_id, title, description, kind gathering|wedding|birthday|memorial|other, calendar solar|lunar, year?, month, day,
repeats_yearly, time_text?, location?)`. A repeating event recurs every year on its solar or lunar date (a lunar one therefore
moves in the solar calendar); a one-off needs its year. Admins create/edit/delete (audit-logged); everyone who can read the tree
sees them.

## Reading the calendar

`GET /calendar/month?year&month` (the month's days with their lunar dates, plus every giỗ and event in it),
`GET /calendar/upcoming?days` (default 30), `GET /calendar/convert` (solar↔lunar). All reads follow the tree's visibility.
"Today" is Vietnam's date (UTC+7).

## Calendar link (.ics)

A phone calendar cannot send a login cookie, so the feed lives at a **secret URL**: `GET /calendar/feed/<token>.ics`, one token
per tree (`trees.calendar_token`), created/regenerated/disabled by an admin; any signed-in user of the tree can read the link to
subscribe. Treat the URL like Google Calendar's "secret address": anyone who has it sees the giỗ and events; regenerating it
cuts old subscribers off. The feed lists occurrences from 30 days ago to 2 years ahead as all-day events with stable UIDs.

## Reminders

Per user: `reminder_days` (subset of 0, 1, 3, 7, 14, 30 days before; default 7 and 1) and `reminder_email` (default on).
A **worker** (`scripts/run_reminders.py`, a `worker` service in the compose file) runs every hour and, for each tree, creates an
in-web **notification** for every active user whose reminder days match an occurrence, then emails them if SMTP is configured.
Idempotent: `notifications` has a unique `(user_id, dedupe_key)`, so running the job again (or catching up after the worker was
down) never duplicates anything. The web app shows a bell with the unread count in the header.

## Non-goals (later)

Invitation cards and RSVP (GĐ9), birthdays of living members (privacy), per-person leap-month giỗ preference, push/Zalo
notifications, editing an occurrence of a repeating event alone.
