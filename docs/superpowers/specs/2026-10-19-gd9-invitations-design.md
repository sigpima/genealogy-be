# GĐ9 — Online invitations (thiệp mời) and RSVP — Design

Date: 2026-10-19
Status: Approved to build by the owner ("làm liên tục các giai đoạn còn lại"); realises roadmap F4. Choices below are mine.

## Goal

An admin sends a họp họ / giỗ Tổ / cưới hỏi invitation as a **link** (pasted into a Zalo group or an email). The recipient opens a
nice card **without logging in** and answers Tham dự / Không / Chưa chắc with the number of people; the admin sees who is coming.

## Model

- **Card** (`event_cards`): one invitation for one **occurrence** of an event (a yearly giỗ Tổ needs its date): `event_id`, `date` (solar),
  a secret `token`, an optional `message` (lời mời), an optional `closes_on` deadline and a `closed` switch. A date that is not an
  occurrence of the event is refused. Several cards per event are fine (one per year).
- **Response** (`event_rsvps`): `name`, `response` yes|no|maybe (NULL = invited but silent), `party_size` 1–20, `note`, and its own secret
  `invitee_token`.
- Two ways in, same URL shape `/thiep/<token>`:
  - the card's **open link** (one link for everybody): the guest types a name and answers; they get back a personal token, kept in
    their browser, so they can change the answer later;
  - **personal links**: the admin lists names, each gets its own link; the page greets them by name.

## What a stranger with a link sees (no login, no tree cookie)

The family name, the event (title, kind, solar **and lunar** date, time), the place (name, address, and a directions link when it has GPS —
the admin chose that place for the event), the message, the totals (how many people said yes) and their own answer. **Never other guests'
names or notes.** Unknown tokens are 404. A closed card or a passed deadline still shows but refuses answers (409).

## What the admin sees

Per card: the link, totals (yes / no / maybe / no answer, **people coming** = sum of party sizes of the yes answers), the full response list
with names and notes, add personal invitees, delete a response, edit message/deadline/closed, delete the card, **download the list as CSV**.
Cards live in the calendar's day view next to the event. Creating, editing and deleting a card is audit-logged.

## Safety

Tokens are `secrets.token_urlsafe(24)`. Free text is stored and shown as plain text (React escapes it). A card accepts at most 500 responses
(an open link must not become a storage dump); the general rate limiting arrives with GĐ11's hardening.

## Non-goals (later)

Emailing invitations from the app, reminders to the silent, a headcount per household, seating, payments/contributions, QR codes.
