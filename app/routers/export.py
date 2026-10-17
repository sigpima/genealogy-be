"""Full data export of one tree as JSON (admin only, audited). Meant for taking your data elsewhere or keeping a
human-readable copy next to the database backup; the files themselves (photos, scans) are in the backup, not here."""

import datetime
import decimal
import json
from typing import Any

from fastapi import APIRouter, Depends, Response
from sqlalchemy import inspect, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.core.permissions import get_write_context
from app.core.privacy import field_levels
from app.core.tenancy import TreeContext
from app.db.session import get_db
from app.models.article import Article, ArticleMember, GenerationWord, TimelineEntry
from app.models.audit_log import AuditLog
from app.models.branch import Branch
from app.models.change_request import ChangeRequest
from app.models.event import Event
from app.models.event_card import EventCard, EventRsvp
from app.models.marriage import Marriage
from app.models.media import Media
from app.models.member import Member
from app.models.place import Place
from app.models.user import User

router = APIRouter(prefix="/export", tags=["export"])

#: secrets and credentials never leave through an export: they would turn a data copy into a set of keys
SECRET_COLUMNS = {"hashed_password", "token", "invitee_token", "calendar_token"}
FORMAT_VERSION = 1


def _plain(value: Any) -> Any:
    if isinstance(value, (datetime.datetime, datetime.date)):
        return value.isoformat()
    if isinstance(value, decimal.Decimal):
        return float(value)
    return value


def rows_of(objects: list[Any], *, skip: set[str] = SECRET_COLUMNS) -> list[dict[str, Any]]:
    return [{c.key: _plain(getattr(o, c.key)) for c in inspect(type(o)).mapper.column_attrs if c.key not in skip} for o in objects]


async def _all(db: AsyncSession, statement) -> list[Any]:
    return list((await db.execute(statement)).scalars().all())


@router.get("/data.json")
async def export_data(
    include_audit: bool = False, db: AsyncSession = Depends(get_db), ctx: TreeContext = Depends(get_write_context)
) -> Response:
    tree_id = ctx.tree.id
    members = await _all(db, select(Member).where(Member.tree_id == tree_id).order_by(Member.id))
    ids = [m.id for m in members]
    articles = await _all(db, select(Article).where(Article.tree_id == tree_id).order_by(Article.id))
    events = await _all(db, select(Event).where(Event.tree_id == tree_id).order_by(Event.id))
    cards = await _all(db, select(EventCard).where(EventCard.tree_id == tree_id).order_by(EventCard.id))
    card_ids = [c.id for c in cards]
    data: dict[str, Any] = {
        "format_version": FORMAT_VERSION,
        "exported_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "tree": {"id": ctx.tree.id, "name": ctx.tree.name, "slug": ctx.tree.slug},
        "privacy": await field_levels(db, tree_id),
        "members": rows_of(members),
        "marriages": rows_of(await _all(db, select(Marriage).where(Marriage.member_id.in_(ids)).order_by(Marriage.id))),
        "branches": rows_of(await _all(db, select(Branch).where(Branch.tree_id == tree_id).order_by(Branch.id))),
        "places": rows_of(await _all(db, select(Place).where(Place.tree_id == tree_id).order_by(Place.id))),
        "media": rows_of(await _all(db, select(Media).where(Media.tree_id == tree_id).order_by(Media.id))),
        "articles": rows_of(articles),  # drafts included: this is the owner's copy
        "article_members": rows_of(
            await _all(db, select(ArticleMember).where(ArticleMember.article_id.in_([a.id for a in articles])))
        ),
        "timeline": rows_of(await _all(db, select(TimelineEntry).where(TimelineEntry.tree_id == tree_id).order_by(TimelineEntry.id))),
        "generation_words": rows_of(await _all(db, select(GenerationWord).where(GenerationWord.tree_id == tree_id).order_by(GenerationWord.generation))),
        "events": rows_of(events),
        "event_cards": rows_of(cards),
        "event_rsvps": rows_of(await _all(db, select(EventRsvp).where(EventRsvp.card_id.in_(card_ids)).order_by(EventRsvp.id))),
        "change_requests": rows_of(await _all(db, select(ChangeRequest).where(ChangeRequest.tree_id == tree_id).order_by(ChangeRequest.id))),
        "users": rows_of(await _all(db, select(User).where(User.tree_id == tree_id).order_by(User.id))),
    }
    if include_audit:
        data["audit_log"] = rows_of(await _all(db, select(AuditLog).where(AuditLog.tree_id == tree_id).order_by(AuditLog.id)))
    audit.record(db, tree_id=tree_id, actor=ctx.user, action="data.export", details={"members": len(members), "include_audit": include_audit})
    await db.commit()
    body = json.dumps(data, ensure_ascii=False, indent=1)
    return Response(
        content=body,
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="gia-pha-{ctx.tree.slug}-data.json"'},
    )
