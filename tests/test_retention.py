"""Housekeeping: old read notifications go with the hourly job; the audit log is only ever pruned when the owner asks; an index on members.parent_id."""

from datetime import date

import pytest
from sqlalchemy import text

from app.cli import run
from app.core.retention import prune_audit, prune_notifications
from app.core.tenants import create_tree, create_user
from tests.test_roles_auth import PASSWORD


@pytest.fixture
async def world(session):
    tree = await create_tree(session, "Họ A", "ho-a")
    user = await create_user(session, email="a@example.com", full_name="A", password=PASSWORD, role="member", tree=tree)
    return tree, user


async def notify(session, tree, user, key, days_old, read):
    await session.execute(
        text(
            "INSERT INTO notifications (user_id, tree_id, kind, title, dedupe_key, created_at, read_at) "
            "VALUES (:u, :t, 'death_anniversary', 'x', :k, now() - make_interval(days => :d), CASE WHEN :r THEN now() ELSE NULL END)"
        ),
        {"u": user.id, "t": tree.id, "k": key, "d": days_old, "r": read},
    )
    await session.commit()


async def remaining(session):
    return {r[0] for r in (await session.execute(text("SELECT dedupe_key FROM notifications"))).all()}


async def test_old_read_notifications_go_and_everything_recent_stays(session, world):
    tree, user = world
    await notify(session, tree, user, "old-read", 120, True)
    await notify(session, tree, user, "recent-read", 10, True)
    await notify(session, tree, user, "old-unread", 120, False)
    await notify(session, tree, user, "ancient-unread", 400, False)
    deleted = await prune_notifications(session)
    assert deleted == 2
    assert await remaining(session) == {"recent-read", "old-unread"}  # an unread reminder is kept for a year, then it is surely dead


async def test_the_reminder_pass_tidies_up_after_itself(session, world, monkeypatch):
    from app.jobs.reminders import send_due_reminders

    tree, user = world
    await notify(session, tree, user, "old-read", 200, True)
    await send_due_reminders(session, today=date(2026, 10, 19))
    assert "old-read" not in await remaining(session)


async def test_the_audit_log_is_only_pruned_on_request_and_by_age(session, world):
    tree, user = world
    for key, age in [("old", 800), ("recent", 30)]:
        await session.execute(
            text("INSERT INTO audit_log (tree_id, actor_name, action, details, created_at) VALUES (:t, 'A', 'member.create', CAST(:d AS jsonb), now() - make_interval(days => :a))"),
            {"t": tree.id, "d": f'{{"k": "{key}"}}', "a": age},
        )
    await session.commit()
    assert await prune_audit(session, days=730) == 1
    left = (await session.execute(text("SELECT details->>'k' FROM audit_log"))).scalars().all()
    assert left == ["recent"]


async def test_the_command_line_needs_to_be_told_what_to_prune(session, world):
    assert (await run(["prune"], session)).startswith("error:")
    out = await run(["prune", "--notifications-days", "90", "--audit-days", "730"], session)
    assert "notifications" in out and "audit" in out
    assert (await run(["prune", "--audit-days", "0"], session)).startswith("error:")  # 0 would wipe the whole log


async def test_the_children_of_a_person_are_found_by_an_index(session):
    names = {r[0] for r in (await session.execute(text("SELECT indexname FROM pg_indexes WHERE tablename = 'members'"))).all()}
    assert "ix_members_parent_id" in names
    log = {r[0] for r in (await session.execute(text("SELECT indexname FROM pg_indexes WHERE tablename = 'audit_log'"))).all()}
    assert "ix_audit_log_tree_id_id" in log
