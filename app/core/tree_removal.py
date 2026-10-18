"""Deleting a whole family: its rows in an order the foreign keys accept, and the list of files to remove after the commit.

The caller owns the transaction and must unlink the returned files only once the commit has succeeded (a failed commit
must not leave a family with its photos gone).
"""

from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.media_files import media_dir, thumbs_dir
from app.models.article import Article, GenerationWord, TimelineEntry
from app.models.audit_log import AuditLog
from app.models.branch import Branch
from app.models.change_request import ChangeRequest
from app.models.event import Event
from app.models.event_card import EventCard
from app.models.media import Media
from app.models.member import Member
from app.models.notification import Notification
from app.models.place import Place
from app.models.tree import Tree
from app.models.user import User


@dataclass
class Removal:
    counts: dict[str, int] = field(default_factory=dict)
    files: list[Path] = field(default_factory=list)

    def unlink(self) -> None:
        for path in self.files:
            path.unlink(missing_ok=True)  # already gone (the data-health page reports those): fine


async def _count(db: AsyncSession, model, tree_id: int) -> int:
    return (await db.execute(select(func.count()).select_from(model).where(model.tree_id == tree_id))).scalar_one()


async def delete_tree_data(db: AsyncSession, tree: Tree) -> Removal:
    removal = Removal()
    removal.counts = {
        "members": await _count(db, Member, tree.id),
        "users": await _count(db, User, tree.id),
        "media": await _count(db, Media, tree.id),
    }
    media = (await db.execute(select(Media).where(Media.tree_id == tree.id))).scalars().all()
    for row in media:
        removal.files.append(media_dir() / row.stored_name)
        if row.thumb_name:
            removal.files.append(thumbs_dir() / row.thumb_name)
    avatars = Path(get_settings().upload_dir) / "avatars"
    for (url,) in (await db.execute(select(Member.avatar_url).where(Member.tree_id == tree.id, Member.avatar_url.is_not(None)))).all():
        removal.files.append(avatars / url.rsplit("/", 1)[-1])
    removal.counts["files"] = len(removal.files)
    # children before parents; members go in one statement (the self-reference is checked at its end)
    for model in (Notification, ChangeRequest, AuditLog, EventCard, Event, Media, TimelineEntry, Article, GenerationWord, Branch, Member, Place, User):
        await db.execute(delete(model).where(model.tree_id == tree.id))
    await db.delete(tree)  # site_settings go with it (ON DELETE CASCADE)
    return removal
