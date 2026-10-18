"""Facts about the server itself for the superadmin's health page (see the superadmin console design). Read-only apart from `set_state`."""

import datetime
import shutil
from pathlib import Path
from typing import Literal

from pydantic import BaseModel
from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.media import Media
from app.models.system_state import SystemState

WORKER_STALE_AFTER = datetime.timedelta(hours=3)  # the worker runs hourly
LOW_DISK_PERCENT = 15


class DatabaseHealth(BaseModel):
    ok: bool
    revision: str | None = None


class WorkerHealth(BaseModel):
    state: Literal["ok", "stale", "unknown"]
    last_run: datetime.datetime | None = None
    age_minutes: int | None = None


class DiskHealth(BaseModel):
    total_bytes: int
    free_bytes: int
    free_percent: int


class StorageHealth(BaseModel):
    media_bytes: int
    avatar_bytes: int


async def set_state(db: AsyncSession, key: str, value: str) -> None:
    statement = insert(SystemState).values(key=key, value=value)
    await db.execute(statement.on_conflict_do_update(index_elements=[SystemState.key], set_={"value": value, "updated_at": func.now()}))


async def database_health(db: AsyncSession) -> DatabaseHealth:
    try:
        revision = (await db.execute(text("SELECT version_num FROM alembic_version"))).scalar_one_or_none()
        return DatabaseHealth(ok=True, revision=revision)
    except Exception:  # noqa: BLE001 - "can I ask the database anything" is the whole question
        return DatabaseHealth(ok=False)


async def worker_health(db: AsyncSession, now: datetime.datetime) -> WorkerHealth:
    row = await db.get(SystemState, "reminders.last_run")
    if row is None:
        return WorkerHealth(state="unknown")
    try:
        last = datetime.datetime.fromisoformat(row.value)
    except ValueError:
        return WorkerHealth(state="unknown")
    if last.tzinfo is None:
        last = last.replace(tzinfo=datetime.timezone.utc)
    age = now - last
    return WorkerHealth(
        state="stale" if age > WORKER_STALE_AFTER else "ok",
        last_run=last,
        age_minutes=max(0, int(age.total_seconds() // 60)),
    )


def disk_health(path: Path) -> DiskHealth:
    usage = shutil.disk_usage(path if path.exists() else path.parent if path.parent.exists() else Path("/"))
    return DiskHealth(total_bytes=usage.total, free_bytes=usage.free, free_percent=int(usage.free * 100 // usage.total) if usage.total else 0)


async def storage_health(db: AsyncSession, upload_dir: Path) -> StorageHealth:
    media = int((await db.execute(select(func.coalesce(func.sum(Media.size), 0)))).scalar_one() or 0)
    avatars = 0
    try:
        for entry in (upload_dir / "avatars").iterdir():
            try:
                avatars += entry.stat().st_size if entry.is_file() else 0
            except OSError:
                pass
    except OSError:
        pass
    return StorageHealth(media_bytes=media, avatar_bytes=avatars)
