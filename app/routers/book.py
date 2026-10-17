"""The "quyển phả" PDF (admins only; see the GĐ10 design). Built in a worker thread; every export is audit-logged."""

import asyncio
import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.core.book import BookData, BookOptions, build_book
from app.core.config import get_settings
from app.core.permissions import get_write_context
from app.core.tenancy import TreeContext
from app.core.tree_layout import load_branches, load_layout
from app.db.session import get_db
from app.models.article import Article, GenerationWord, TimelineEntry
from app.models.marriage import Marriage
from app.models.place import Place

router = APIRouter(tags=["book"])


@router.get("/book.pdf")
async def book_pdf(
    chronicles: bool = True,
    profiles: bool = True,
    diagram: bool = True,
    notes: bool = True,
    photos: bool = False,
    contacts: bool = False,
    max_generation: int | None = Query(default=None, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    ctx: TreeContext = Depends(get_write_context),
) -> Response:
    """A printable book of this family. Contacts and drafts are never included unless asked (drafts: never)."""
    options = BookOptions(chronicles, profiles, diagram, notes, photos, contacts, max_generation)
    branches = await load_branches(db, ctx.tree.id)
    layout = await load_layout(db, ctx.tree.id, branches)
    ids = list(layout.by_id)
    marriages = (await db.execute(select(Marriage).where(Marriage.member_id.in_(ids)).order_by(Marriage.marriage_year.is_(None), Marriage.marriage_year, Marriage.id))).scalars().all()
    spouses_of: dict[int, list] = {}
    for marriage in marriages:
        spouse = layout.by_id.get(marriage.spouse_id)
        if spouse is not None:
            spouses_of.setdefault(marriage.member_id, []).append((spouse, marriage.marriage_year))
    articles = (
        await db.execute(
            select(Article).where(Article.tree_id == ctx.tree.id, Article.status == "published").order_by(Article.pinned.desc(), Article.position, Article.id)
        )
    ).scalars().all()
    timeline = (await db.execute(select(TimelineEntry).where(TimelineEntry.tree_id == ctx.tree.id).order_by(TimelineEntry.year, TimelineEntry.month.asc().nulls_first(), TimelineEntry.day.asc().nulls_first(), TimelineEntry.id))).scalars().all()
    words = (await db.execute(select(GenerationWord).where(GenerationWord.tree_id == ctx.tree.id).order_by(GenerationWord.generation))).scalars().all()
    places = {p.id: p for p in (await db.execute(select(Place).where(Place.tree_id == ctx.tree.id))).scalars().all()}
    upload_dir = Path(get_settings().upload_dir)
    avatar_paths = {
        m.id: upload_dir / "avatars" / m.avatar_url.rsplit("/", 1)[-1] for m in layout.by_id.values() if m.avatar_url and photos
    }
    data = BookData(
        tree_name=ctx.tree.name,
        layout=layout,
        spouses_of=spouses_of,
        articles=list(articles),
        timeline=list(timeline),
        words=list(words),
        branches={b.id: (b.name, b.color) for b in branches},
        places=places,
        avatar_paths=avatar_paths,
        generated_on=datetime.date.today(),
        options=options,
    )
    pdf = await asyncio.to_thread(build_book, data)
    audit.record(
        db,
        tree_id=ctx.tree.id,
        actor=ctx.user,
        action="book.export",
        details={
            "chronicles": chronicles, "profiles": profiles, "diagram": diagram, "notes": notes, "photos": photos,
            "contacts": contacts, "max_generation": max_generation, "members": len(layout.order), "bytes": len(pdf),
        },
    )
    await db.commit()
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="gia-pha-{ctx.tree.slug}.pdf"'},
    )
