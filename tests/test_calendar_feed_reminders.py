"""GĐ5: the secret .ics link, per-user reminder settings, the hourly reminder job and in-web notifications."""

from datetime import date

import pytest
from sqlalchemy import select

from app.core.tenants import create_tree, create_user
from tests.test_roles_auth import PASSWORD, login, set_user


@pytest.fixture
async def world(session):
    tree_a = await create_tree(session, "Họ A", "ho-a")
    tree_b = await create_tree(session, "Họ B", "ho-b")
    for key, role, tree in [
        ("admin_a", "admin", tree_a),
        ("member_a", "member", tree_a),
        ("quiet_a", "member", tree_a),
        ("admin_b", "admin", tree_b),
    ]:
        await create_user(session, email=f"{key}@example.com", full_name=key, password=PASSWORD, role=role, tree=tree)
    return {"tree_a": tree_a, "tree_b": tree_b}


async def signed_in(make_client, who):
    c = make_client()
    assert (await login(c, f"{who}@example.com")).status_code == 200
    return c


async def add(c, name, parent_id=None, **extra):
    r = await c.post("/members", json={"full_name": name, "parent_id": parent_id, **extra})
    assert r.status_code == 201, r.text
    return r.json()["id"]


@pytest.fixture
async def setup(world, make_client, monkeypatch):
    monkeypatch.setattr("app.core.calendar_items.vn_today", lambda: date(2024, 9, 10))
    admin = await signed_in(make_client, "admin_a")
    root = await add(admin, "Tổ")
    await add(admin, "Ông A", root, death_year=2001, death_month=8, death_day=15, death_is_lunar=True)  # giỗ 2024-09-17
    return {"admin": admin, "make_client": make_client}


# ------------------------------------------------------------------ the .ics link


async def test_the_link_starts_disabled_and_only_admins_manage_it(setup):
    admin, mk = setup["admin"], setup["make_client"]
    assert (await admin.get("/calendar/subscription")).json() == {"enabled": False, "path": None}
    member = await signed_in(mk, "member_a")
    assert (await member.post("/calendar/subscription")).status_code == 403
    assert (await member.delete("/calendar/subscription")).status_code == 403
    enabled = (await admin.post("/calendar/subscription")).json()
    assert enabled["enabled"] is True and enabled["path"].startswith("/calendar/feed/") and enabled["path"].endswith(".ics")
    assert (await member.get("/calendar/subscription")).json() == enabled  # members can read it to subscribe
    assert (await mk().get("/calendar/subscription")).status_code == 401


async def test_the_feed_needs_no_login_and_lists_the_giỗ(setup):
    admin, mk = setup["admin"], setup["make_client"]
    path = (await admin.post("/calendar/subscription")).json()["path"]
    response = await mk().get(path)  # a stranger's phone: no cookies
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/calendar")
    text = response.text
    assert text.startswith("BEGIN:VCALENDAR") and text.rstrip().endswith("END:VCALENDAR")
    assert "VERSION:2.0" in text and "PRODID:" in text
    assert "DTSTART;VALUE=DATE:20240917" in text
    assert "SUMMARY:Giỗ Ông A" in text.replace("\r\n ", "")
    assert "15/8 âm lịch" in text.replace("\r\n ", "") and "lần thứ 23" in text.replace("\r\n ", "")
    assert "UID:" in text and text.count("BEGIN:VEVENT") == text.count("END:VEVENT") >= 2  # 2024 and 2025 and more
    assert all(len(line.encode()) <= 75 for line in text.split("\r\n")), "lines must be folded at 75 octets"


async def test_the_feed_includes_events_and_escapes_text(setup):
    admin, mk = setup["admin"], setup["make_client"]
    await admin.post("/events", json={
        "title": "Họp họ, ăn cơm; vui", "kind": "gathering", "calendar": "solar", "month": 9, "day": 20, "year": 2024,
        "location": "Nhà thờ", "description": "Mang theo\nảnh cũ", "time_text": "08:30",
    })
    path = (await admin.post("/calendar/subscription")).json()["path"]
    text = (await mk().get(path)).text.replace("\r\n ", "")
    assert "SUMMARY:Họp họ\\, ăn cơm\\; vui" in text
    assert "LOCATION:Nhà thờ" in text and "Mang theo\\nảnh cũ" in text
    assert "DTSTART;VALUE=DATE:20240920" in text


async def test_unknown_regenerated_and_disabled_tokens_stop_working(setup):
    admin, mk = setup["admin"], setup["make_client"]
    assert (await mk().get("/calendar/feed/not-a-token.ics")).status_code == 404
    first = (await admin.post("/calendar/subscription")).json()["path"]
    second = (await admin.post("/calendar/subscription")).json()["path"]
    assert first != second
    assert (await mk().get(first)).status_code == 404
    assert (await mk().get(second)).status_code == 200
    assert (await admin.delete("/calendar/subscription")).status_code == 204
    assert (await mk().get(second)).status_code == 404
    assert (await admin.get("/calendar/subscription")).json()["enabled"] is False


async def test_a_feed_only_shows_its_own_family(setup, world):
    other = await signed_in(setup["make_client"], "admin_b")
    await add(other, "Người họ B")
    path_b = (await other.post("/calendar/subscription")).json()["path"]
    text = (await setup["make_client"]().get(path_b)).text
    assert "Ông A" not in text


# ------------------------------------------------------------------ reminder settings


async def test_reminder_settings_default_and_validation(setup):
    admin = setup["admin"]
    assert (await admin.get("/calendar/reminders")).json() == {"days": [7, 1], "email": True}
    ok = await admin.put("/calendar/reminders", json={"days": [1, 14, 14, 3], "email": False})
    assert ok.status_code == 200 and ok.json() == {"days": [14, 3, 1], "email": False}
    assert (await admin.get("/calendar/reminders")).json() == {"days": [14, 3, 1], "email": False}
    assert (await admin.put("/calendar/reminders", json={"days": [2], "email": True})).status_code == 422
    assert (await admin.put("/calendar/reminders", json={"days": [], "email": True})).status_code == 200  # none = no reminders
    assert (await setup["make_client"]().get("/calendar/reminders")).status_code == 401


# ------------------------------------------------------------------ the job and notifications


async def test_the_job_notifies_each_user_once_per_matching_day(setup, session, monkeypatch):
    from app.jobs.reminders import send_due_reminders

    admin, mk = setup["admin"], setup["make_client"]
    quiet = await signed_in(mk, "quiet_a")
    await quiet.put("/calendar/reminders", json={"days": [], "email": False})
    sent = []
    monkeypatch.setattr("app.jobs.reminders.send_email", lambda to, subject, body: sent.append(to))
    monkeypatch.setenv("SMTP_HOST", "smtp.test")
    from app.core.config import get_settings

    get_settings.cache_clear()

    result = await send_due_reminders(session, date(2024, 9, 10))  # 7 days before 2024-09-17
    assert result == {"notifications": 2, "emails": 2}  # admin_a and member_a (defaults 7,1); quiet_a opted out, tree B is empty
    assert sorted(sent) == ["admin_a@example.com", "member_a@example.com"]
    again = await send_due_reminders(session, date(2024, 9, 10))
    assert again == {"notifications": 0, "emails": 0}  # idempotent: no duplicates when the job runs again
    nothing = await send_due_reminders(session, date(2024, 9, 12))  # 5 days before: nobody asked for that
    assert nothing == {"notifications": 0, "emails": 0}
    tomorrow = await send_due_reminders(session, date(2024, 9, 16))  # 1 day before
    assert tomorrow == {"notifications": 2, "emails": 2}

    member = await signed_in(mk, "member_a")
    body = (await member.get("/notifications")).json()
    assert body["unread"] == 2 and len(body["items"]) == 2
    newest = body["items"][0]
    assert "Ông A" in newest["title"] and newest["read"] is False and newest["link"]
    assert (await (await signed_in(mk, "quiet_a")).get("/notifications")).json() == {"unread": 0, "items": []}


async def test_emails_respect_the_user_choice_and_smtp_settings(setup, session, monkeypatch):
    from app.core.config import get_settings
    from app.jobs.reminders import send_due_reminders

    member = await signed_in(setup["make_client"], "member_a")
    await member.put("/calendar/reminders", json={"days": [7], "email": False})
    await (await signed_in(setup["make_client"], "quiet_a")).put("/calendar/reminders", json={"days": [], "email": False})
    sent = []
    monkeypatch.setattr("app.jobs.reminders.send_email", lambda to, subject, body: sent.append(to))
    # no SMTP configured: notifications still happen, nothing is emailed
    result = await send_due_reminders(session, date(2024, 9, 10))
    assert result["notifications"] == 2 and result["emails"] == 0 and sent == []
    # SMTP configured but member_a said no email: only the admin is emailed
    monkeypatch.setenv("SMTP_HOST", "smtp.test")
    get_settings.cache_clear()
    await set_user(session, "admin_a@example.com", full_name="admin_a")  # no-op, keeps the fixture honest
    again = await send_due_reminders(session, date(2024, 9, 16))
    assert again["notifications"] == 1  # only the admin asked for 1 day before (member_a chose just 7)
    assert sent == ["admin_a@example.com"]


async def test_a_failing_mail_server_does_not_stop_the_job(setup, session, monkeypatch):
    from app.core.config import get_settings
    from app.jobs.reminders import send_due_reminders

    def boom(*args):
        raise OSError("smtp down")

    await (await signed_in(setup["make_client"], "quiet_a")).put("/calendar/reminders", json={"days": [], "email": False})
    monkeypatch.setattr("app.jobs.reminders.send_email", boom)
    monkeypatch.setenv("SMTP_HOST", "smtp.test")
    get_settings.cache_clear()
    result = await send_due_reminders(session, date(2024, 9, 10))
    assert result["notifications"] == 2 and result["emails"] == 0


async def test_disabled_users_get_nothing(setup, session):
    from app.jobs.reminders import send_due_reminders

    await set_user(session, "member_a@example.com", status="disabled")
    # admin_a and quiet_a (member_a is disabled)
    assert (await send_due_reminders(session, date(2024, 9, 10)))["notifications"] == 2


async def test_notifications_can_be_marked_read(setup, session):
    from app.jobs.reminders import send_due_reminders

    await send_due_reminders(session, date(2024, 9, 10))
    await send_due_reminders(session, date(2024, 9, 16))
    member = await signed_in(setup["make_client"], "member_a")
    items = (await member.get("/notifications")).json()["items"]
    one = await member.post("/notifications/read", json={"ids": [items[0]["id"]]})
    assert one.status_code == 200 and one.json()["unread"] == 1
    allread = await member.post("/notifications/read", json={})
    assert allread.json()["unread"] == 0
    assert all(n["read"] for n in (await member.get("/notifications")).json()["items"])
    # somebody else's notification id is silently ignored
    admin = setup["admin"]
    admin_items = (await admin.get("/notifications")).json()["items"]
    await member.post("/notifications/read", json={"ids": [admin_items[0]["id"]]})
    assert (await admin.get("/notifications")).json()["unread"] == 2
    assert (await setup["make_client"]().get("/notifications")).status_code == 401
