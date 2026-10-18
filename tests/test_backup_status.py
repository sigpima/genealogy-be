"""Admin console: read-only status of the backups the host script writes (no trigger, no download, no whole-database numbers)."""

import datetime

import pytest

from app.core.backup_status import read_backup_status
from app.core.calendar_items import VN_TIMEZONE
from app.core.config import get_settings
from app.core.tenants import create_tree, create_user
from tests.test_roles_auth import PASSWORD, login

NOW = datetime.datetime(2026, 10, 18, 12, 0, tzinfo=VN_TIMEZONE)


def backup(directory, stamp, dump=b"d" * 100, uploads=b"u" * 50, with_dump=True):
    folder = directory / f"gia-pha-{stamp}"
    folder.mkdir(parents=True)
    if with_dump:
        (folder / "database.dump").write_bytes(dump)
        (folder / "uploads.tar.gz").write_bytes(uploads)
    return folder


def test_a_missing_directory_means_never(tmp_path):
    status = read_backup_status(tmp_path / "nope", NOW)
    assert status.model_dump() == {"state": "never", "last_at": None, "age_days": None, "size_bytes": None, "kept": 0}


def test_an_empty_directory_means_never(tmp_path):
    assert read_backup_status(tmp_path, NOW).state == "never"


def test_folders_without_a_dump_or_with_odd_names_are_ignored(tmp_path):
    backup(tmp_path, "20261017-020000", with_dump=False)
    (tmp_path / "gia-pha-not-a-date").mkdir()
    (tmp_path / "other-folder").mkdir()
    (tmp_path / "gia-pha-20261017-020000.partial").mkdir()
    (tmp_path / "gia-pha-20260230-020000").mkdir()  # not a real date
    (tmp_path / "stray-file.txt").write_text("x")
    assert read_backup_status(tmp_path, NOW).state == "never"


def test_the_newest_valid_backup_is_reported_with_its_size_and_the_count(tmp_path):
    backup(tmp_path, "20261010-020000")
    backup(tmp_path, "20261017-020000", dump=b"d" * 1000, uploads=b"u" * 234)
    status = read_backup_status(tmp_path, NOW)
    assert status.state == "ok" and status.kept == 2
    assert status.size_bytes == 1234
    assert status.last_at == datetime.datetime(2026, 10, 17, 2, 0, tzinfo=VN_TIMEZONE)
    assert status.age_days == 1


def test_a_backup_older_than_a_week_is_old(tmp_path):
    backup(tmp_path, "20261010-020000")
    assert read_backup_status(tmp_path, NOW).state == "old"  # 8 days
    backup(tmp_path, "20261014-020000")
    assert read_backup_status(tmp_path, NOW).state == "ok"  # 4 days


def test_a_missing_uploads_archive_still_counts_with_the_dump_size(tmp_path):
    folder = backup(tmp_path, "20261017-020000")
    (folder / "uploads.tar.gz").unlink()
    assert read_backup_status(tmp_path, NOW).size_bytes == 100


@pytest.fixture
async def world(session):
    tree = await create_tree(session, "Họ A", "ho-a")
    for key, role in [("admin_a", "admin"), ("member_a", "member")]:
        await create_user(session, email=f"{key}@example.com", full_name=key, password=PASSWORD, role=role, tree=tree)
    return tree


def use_backup_dir(monkeypatch, directory):
    monkeypatch.setenv("BACKUP_DIR", str(directory))
    get_settings.cache_clear()


async def test_the_endpoint_reports_status_without_whole_database_numbers(world, make_client, monkeypatch, tmp_path):
    use_backup_dir(monkeypatch, tmp_path)
    backup(tmp_path, f"{datetime.datetime.now(VN_TIMEZONE):%Y%m%d-%H%M%S}")
    (tmp_path / "gia-pha-20200101-000000").mkdir()
    admin = make_client()
    assert (await login(admin, "admin_a@example.com")).status_code == 200
    body = (await admin.get("/admin/backup-status")).json()
    assert body["state"] == "ok" and body["kept"] == 1 and body["age_days"] == 0
    assert set(body) == {"state", "last_at", "age_days", "size_bytes", "kept"}  # no members count, no names, no paths


async def test_the_overview_asks_for_a_backup_when_there_is_none_or_it_is_old(world, make_client, monkeypatch, tmp_path):
    use_backup_dir(monkeypatch, tmp_path)
    admin = make_client()
    assert (await login(admin, "admin_a@example.com")).status_code == 200
    items = {i["key"]: i for i in (await admin.get("/admin/overview")).json()["items"]}
    assert items["backup_old"]["kind"] == "task" and items["backup_old"]["href"] == "/admin/sao-luu"
    backup(tmp_path, f"{datetime.datetime.now(VN_TIMEZONE):%Y%m%d-%H%M%S}")
    items = {i["key"]: i for i in (await admin.get("/admin/overview")).json()["items"]}
    assert "backup_old" not in items


async def test_members_403_and_guests_401(world, make_client):
    member = make_client()
    assert (await login(member, "member_a@example.com")).status_code == 200
    assert (await member.get("/admin/backup-status")).status_code == 403
    assert (await make_client().get("/admin/backup-status")).status_code == 401
