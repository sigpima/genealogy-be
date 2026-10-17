# GĐ4 — Change requests, review and audit log — Design

Date: 2026-10-18
Status: Approved to build by the owner ("tiếp tục giai đoạn 4"); realises roadmap item E and decision D5 ("admin nhập hàng
loạt + thành viên gửi yêu cầu cập nhật"). The choices below are mine where the owner did not specify.

## Goal

Let the whole family help fill the tree **without** letting anyone but an admin change it: a member proposes, an admin sees
old vs new side by side and approves or rejects. Every change to the tree, however it was made, is written to a log.

## Rules

- **Who proposes:** any signed-in, active user of the tree (members; admins may too). Guests cannot. Members still cannot write
  to `/members/*`; a request is the only door.
- **Three kinds** (`kind`):
  - `edit` — new values for some fields of one person: name, gender, years/months/days + calendar flags, hometown, residence,
    courtesy name, title, phone, email, burial place + GPS, birth order, adoption, notes. **Not** `parent_id`/`mother_id`
    (structure stays with admins).
  - `add_child` — a new child (same fields, plus a name) under the person.
  - `report` — free text ("báo sai / bổ sung"); approving it only acknowledges it, the admin edits by hand.
- A proposal is validated when sent, by the same rules as `PATCH`/`POST` (merged onto the person's current data), so an
  impossible date never reaches the admin. A request that changes nothing is refused (422). `report` needs a message.
- The request stores `changes` (the proposed fields) and `base` (the person's values for those fields **at the time of
  sending**), so the reviewer can see "đã thay đổi từ lúc gửi" when the tree moved on in the meantime.
- **Review (admin only, per tree):** approve applies the change through the same code as a direct edit and writes the audit
  log (actor = the reviewer, linked to the request); reject needs a reason. Approving can fail (person deleted, data no longer
  valid) → 409 and the request stays pending. Decided requests cannot be decided again (409). The requester can cancel their
  own pending request.
- Visibility: an admin sees every request of the tree; anybody else only their own. Another tree's request is 404.
- **Notifications:** an in-web badge with the pending count (admins) and a "my requests" list with the status/reason
  (members). Plus best-effort email (SMTP is already configured for password reset): all active admins of the tree when a
  request arrives, the requester when it is decided. No SMTP, or a failing one, never blocks the action.

## Audit log

`audit_log(id, tree_id, actor_id (SET NULL), actor_name, action, member_id (no FK, survives deletion), member_name, summary,
changes JSON {field: [old, new]}, request_id (SET NULL), created_at)`. Written **in the same transaction** as the change, for:
member create/update/delete/split/avatar, marriage create/update, CSV import (one entry per changed person), branch
create/update/delete, and request decisions. `GET /audit` (admin): filters `member_id`, `limit`/`offset`, newest first.
Phone/email values are in the log (admins only see it).

## Frontend

- Panel (non-admin, signed in): "Đề xuất chỉnh sửa" opens a dialog with the three kinds; the edit form is prefilled and only
  changed fields are sent.
- `/yeu-cau`: admins get "Chờ duyệt / Đã xử lý" with an old→new table per request and Duyệt / Từ chối; everybody else sees
  their own requests and can cancel pending ones. Sidebar item "Yêu cầu" with the pending count.
- `/nhat-ky` (admin): the log, filterable by person; the panel links to it ("Lịch sử").

## Non-goals (later)

Per-field privacy (GĐ11), proposing structural changes (parent/mother/marriages), proposing photos, request comments/threads,
undo from the log, audit of user/role changes and settings, retention policy.
