"""Superadmin console: server health (database, reminder worker, e-mail, disk, storage) and the FULL backup status."""

import datetime
import shutil
from collections import namedtuple

import pytest
from sqlalchemy import text

from app.core.calendar_items import VN_TIMEZONE
from app.core.config import get_settings
from app.core.tenants import create_tree, create_user
from app.jobs.reminders import send_due_reminders
from tests.test_roles_auth import PASSWORD, login

Usage = namedtuple("Usage", "total used free")


@pytest.fixture
async def world(session):
    tree = await create_tree(session, "Họ A", "ho-a")
    await create_user(session, email="root@example.com", full_name="Root", password=PASSWORD, role="superadmin", tree=None)
    await create_user(session, email="admin_a@example.com", full_name="Admin", password=PASSWORD, role="admin", tree=tree)
    return {"tree": tree, "session": session}


async def signed_in(make_client, who):
    c = make_client()
    assert (await login(c, f"{who}@example.com")).status_code == 200
    return c


async def health(c):
    r = await c.get("/platform/health")
    assert r.status_code == 200, r.text
    return r.json()


async def set_heartbeat(session, hours_ago):
    when = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=hours_ago)).isoformat()
    await session.execute(
        text("INSERT INTO system_state (key, value) VALUES ('reminders.last_run', :v) ON CONFLICT (key) DO UPDATE SET value = :v"), {"v": when}
    )
    await session.commit()


def stamp(days_ago=0):
    return f"{datetime.datetime.now(VN_TIMEZONE) - datetime.timedelta(days=days_ago):%Y%m%d-%H%M%S}"


def backup(directory, when, members=None, manifest=None):
    folder = directory / f"gia-pha-{when}"
    folder.mkdir(parents=True)
    (folder / "database.dump").write_bytes(b"d" * 100)
    (folder / "uploads.tar.gz").write_bytes(b"u" * 20)
    if manifest is not None:
        (folder / "MANIFEST.txt").write_text(manifest)
    elif members is not None:
        (folder / "MANIFEST.txt").write_text(f"created_at=x\nmembers={members}\nupload_files=3\n")
    return folder


async def test_the_reminder_job_leaves_a_heartbeat(world, make_client):
    root = await signed_in(make_client, "root")
    assert (await health(root))["worker"]["state"] == "unknown"
    await send_due_reminders(world["session"])
    body = (await health(root))["worker"]
    assert body["state"] == "ok" and body["age_minutes"] is not None and body["age_minutes"] < 5 and body["last_run"]


async def test_worker_states_and_the_overview_items(world, make_client):
    root = await signed_in(make_client, "root")
    items = {i["key"] for i in (await root.get("/platform/overview")).json()["items"]}
    assert "worker_stale" not in items  # no row yet: unknown, never a task
    await set_heartbeat(world["session"], 1)
    assert (await health(root))["worker"]["state"] == "ok"
    await set_heartbeat(world["session"], 4)
    assert (await health(root))["worker"]["state"] == "stale"
    items = {i["key"]: i for i in (await root.get("/platform/overview")).json()["items"]}
    assert items["worker_stale"]["href"] == "/he-thong/he-thong" and items["worker_stale"]["kind"] == "task"


async def test_disk_numbers_and_the_low_disk_item(world, make_client, monkeypatch):
    root = await signed_in(make_client, "root")
    monkeypatch.setattr(shutil, "disk_usage", lambda path: Usage(100, 50, 50))
    assert (await health(root))["disk"] == {"total_bytes": 100, "free_bytes": 50, "free_percent": 50}
    assert "disk_low" not in {i["key"] for i in (await root.get("/platform/overview")).json()["items"]}
    monkeypatch.setattr(shutil, "disk_usage", lambda path: Usage(100, 90, 10))
    assert (await health(root))["disk"]["free_percent"] == 10
    assert "disk_low" in {i["key"] for i in (await root.get("/platform/overview")).json()["items"]}


async def test_the_full_backup_status_has_the_whole_database_numbers(world, make_client, monkeypatch, tmp_path):
    monkeypatch.setenv("BACKUP_DIR", str(tmp_path))
    get_settings.cache_clear()
    backup(tmp_path, stamp(3), members=500)
    backup(tmp_path, stamp(1), members=691)
    root = await signed_in(make_client, "root")
    b = (await health(root))["backup"]
    assert b["state"] == "ok" and b["members"] == 691 and b["kept"] == 2
    assert [r["size_bytes"] for r in b["recent"]] == [120, 120] and len(b["recent"]) == 2
    assert b["recent"][0]["last_at"] > b["recent"][1]["last_at"]  # newest first


async def test_a_garbage_or_missing_manifest_gives_no_members_and_no_crash(world, make_client, monkeypatch, tmp_path):
    monkeypatch.setenv("BACKUP_DIR", str(tmp_path))
    get_settings.cache_clear()
    backup(tmp_path, stamp(1), manifest="members=lots\n\x00\x01 not a manifest")
    backup(tmp_path, stamp(2))
    root = await signed_in(make_client, "root")
    b = (await health(root))["backup"]
    assert b["state"] == "ok" and b["members"] is None and b["kept"] == 2


async def test_no_backups_is_never_and_a_task(world, make_client, monkeypatch, tmp_path):
    monkeypatch.setenv("BACKUP_DIR", str(tmp_path / "missing"))
    get_settings.cache_clear()
    root = await signed_in(make_client, "root")
    assert (await health(root))["backup"]["state"] == "never"
    assert "backup_old" in {i["key"] for i in (await root.get("/platform/overview")).json()["items"]}


async def test_email_database_and_storage(world, make_client, monkeypatch, upload_dir):
    root = await signed_in(make_client, "root")
    assert (await health(root))["email"] == {"configured": False}
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    get_settings.cache_clear()
    body = await health(root)
    assert body["email"] == {"configured": True} and "smtp.example.com" not in str(body)
    revision = (await world["session"].execute(text("SELECT version_num FROM alembic_version"))).scalar_one()
    assert body["database"] == {"ok": True, "revision": revision}
    (upload_dir / "avatars").mkdir(exist_ok=True)
    (upload_dir / "avatars" / "x.png").write_bytes(b"a" * 300)
    await world["session"].execute(text("INSERT INTO media (tree_id, kind, original_name, content_type, size, stored_name) VALUES (:t, 'image', 'a.png', 'image/png', 1000, 'abc.png')"), {"t": world["tree"].id})
    await world["session"].commit()
    assert (await health(root))["storage"] == {"media_bytes": 1000, "avatar_bytes": 300}


async def test_only_the_superadmin_and_the_tree_admins_status_stays_small(world, make_client):
    admin = await signed_in(make_client, "admin_a")
    assert (await admin.get("/platform/health")).status_code == 403
    assert (await make_client().get("/platform/health")).status_code == 401
    assert "members" not in (await admin.get("/admin/backup-status")).json()  # the tree admins' view never gained the whole-database number
