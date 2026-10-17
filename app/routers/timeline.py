"""The clan's timeline. Readers as for articles (published material: members, and guests of a public tree); admins write."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.core.audit import diff_values
from app.core.permissions import get_read_context, get_write_context
from app.core.tenancy import TreeContext
from app.db.session import get_db
from app.models.article import Article, TimelineEntry
from app.models.member import Member
from app.schemas.chronicles import TimelineCreate, TimelineRead, TimelineUpdate

router = APIRouter(prefix="/timeline", tags=["timeline"])

FIELDS = ("year", "month", "day", "title", "body", "member_id", "article_id")


def _values(entry: TimelineEntry) -> dict:
    return {name: getattr(entry, name) for name in FIELDS}


async def _check_links(db: AsyncSession, ctx: TreeContext, member_id: int | None, article_id: int | None) -> None:
    if member_id is not None:
        member = await db.get(Member, member_id)
        if member is None or member.tree_id != ctx.tree.id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="member not found")
    if article_id is not None:
        article = await db.get(Article, article_id)
        if article is None or article.tree_id != ctx.tree.id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="article not found")


async def _in_tree(db: AsyncSession, ctx: TreeContext, entry_id: int) -> TimelineEntry:
    entry = await db.get(TimelineEntry, entry_id)
    if entry is None or entry.tree_id != ctx.tree.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="entry not found")
    return entry


async def _read(db: AsyncSession, entry: TimelineEntry) -> TimelineRead:
    member = await db.get(Member, entry.member_id) if entry.member_id is not None else None
    return TimelineRead(member_name=member.full_name if member else None, id=entry.id, **_values(entry))


@router.get("", response_model=list[TimelineRead])
async def list_timeline(db: AsyncSession = Depends(get_db), ctx: TreeContext = Depends(get_read_context)) -> list[TimelineRead]:
    rows = (
        await db.execute(
            select(TimelineEntry)
            .where(TimelineEntry.tree_id == ctx.tree.id)
            .order_by(TimelineEntry.year, TimelineEntry.month.asc().nulls_first(), TimelineEntry.day.asc().nulls_first(), TimelineEntry.id)
        )
    ).scalars().all()
    return [await _read(db, r) for r in rows]


@router.post("", response_model=TimelineRead, status_code=status.HTTP_201_CREATED)
async def create_entry(payload: TimelineCreate, db: AsyncSession = Depends(get_db), ctx: TreeContext = Depends(get_write_context)) -> TimelineRead:
    await _check_links(db, ctx, payload.member_id, payload.article_id)
    entry = TimelineEntry(tree_id=ctx.tree.id, **payload.model_dump())
    db.add(entry)
    await db.flush()
    audit.record(
        db, tree_id=ctx.tree.id, actor=ctx.user, action="timeline.create",
        changes={k: [None, v] for k, v in _values(entry).items() if v is not None},
        details={"entry_id": entry.id, "title": entry.title},
    )
    await db.commit()
    await db.refresh(entry)
    return await _read(db, entry)


@router.put("/{entry_id}", response_model=TimelineRead)
async def update_entry(
    entry_id: int, payload: TimelineUpdate, db: AsyncSession = Depends(get_db), ctx: TreeContext = Depends(get_write_context)
) -> TimelineRead:
    entry = await _in_tree(db, ctx, entry_id)
    await _check_links(db, ctx, payload.member_id, payload.article_id)
    before = _values(entry)
    for name, value in payload.model_dump().items():
        setattr(entry, name, value)
    changes = diff_values(before, _values(entry))
    if changes:
        audit.record(
            db, tree_id=ctx.tree.id, actor=ctx.user, action="timeline.update", changes=changes,
            details={"entry_id": entry.id, "title": entry.title},
        )
    await db.commit()
    await db.refresh(entry)
    return await _read(db, entry)


@router.delete("/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_entry(entry_id: int, db: AsyncSession = Depends(get_db), ctx: TreeContext = Depends(get_write_context)) -> None:
    entry = await _in_tree(db, ctx, entry_id)
    audit.record(
        db, tree_id=ctx.tree.id, actor=ctx.user, action="timeline.delete",
        changes={k: [v, None] for k, v in _values(entry).items() if v is not None},
        details={"entry_id": entry.id, "title": entry.title},
    )
    await db.delete(entry)
    await db.commit()
