"""Read-only status of the backups the host script `scripts/backup.sh` writes (the folder is mounted read-only into the API).

A backup contains EVERY family's data, so a tree admin only learns that one exists, how old and how big: never a download,
never a trigger, never a whole-database count. A folder counts only if it is named `gia-pha-YYYYmmdd-HHMMSS` (a real date, read
as Vietnam time, the admins' calendar) and holds `database.dump`; half-written `.partial` folders and strays are ignored.
"""

import datetime
import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from app.core.calendar_items import VN_TIMEZONE

FOLDER = re.compile(r"^gia-pha-(\d{8})-(\d{6})$")
OLD_AFTER_DAYS = 7


class BackupStatus(BaseModel):
    state: Literal["never", "ok", "old"]
    last_at: datetime.datetime | None = None
    age_days: int | None = None
    size_bytes: int | None = None
    kept: int = 0


def _stamp(name: str) -> datetime.datetime | None:
    match = FOLDER.match(name)
    if not match:
        return None
    try:
        return datetime.datetime.strptime(match.group(1) + match.group(2), "%Y%m%d%H%M%S").replace(tzinfo=VN_TIMEZONE)
    except ValueError:
        return None


def _size(folder: Path) -> int:
    total = 0
    for name in ("database.dump", "uploads.tar.gz"):
        try:
            total += (folder / name).stat().st_size
        except OSError:
            pass
    return total


def read_backup_status(directory: Path, now: datetime.datetime, old_after_days: int = OLD_AFTER_DAYS) -> BackupStatus:
    found: list[tuple[datetime.datetime, Path]] = []
    try:
        entries = list(directory.iterdir())
    except OSError:  # missing, not a directory or unreadable: simply no backups to report
        return BackupStatus(state="never")
    for entry in entries:
        stamp = _stamp(entry.name)
        if stamp is None:
            continue
        try:
            has_dump = (entry / "database.dump").is_file()
        except OSError:  # a folder the API user may not enter (e.g. written with umask 077): not one we can report on
            continue
        if has_dump:
            found.append((stamp, entry))
    if not found:
        return BackupStatus(state="never")
    last_at, newest = max(found)
    age = now - last_at
    return BackupStatus(
        state="old" if age >= datetime.timedelta(days=old_after_days) else "ok",
        last_at=last_at,
        age_days=max(0, age.days),
        size_bytes=_size(newest),
        kept=len(found),
    )
