"""Articles (sử ký): the family's written memory. Admins write; members read published articles and admins also see drafts;
guests read published ones of a public tree. Photos are `media` of the article (signed-in viewers only, see GĐ6)."""

import re

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.core.audit import diff_values
from app.core.media_files import delete_media_files
from app.core.permissions import get_read_context, get_write_context
from app.core.roles import ADMIN_ROLES
from app.core.tenancy import TreeContext
from app.core.text import fold
from app.db.session import get_db
from app.models.article import Article, ArticleMember
from app.models.media import Media
from app.models.member import Member
from app.schemas.chronicles import (
    ARTICLE_KINDS,
    ArticleCreate,
    ArticleRead,
    ArticleSummary,
    ArticleUpdate,
    MemberName,
    Reorder,
)

router = APIRouter(tags=["articles"])

EXCERPT_LENGTH = 160


def _is_admin(ctx: TreeContext) -> bool:
    return ctx.user is not None and ctx.user.role in ADMIN_ROLES


def make_slug(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", fold(title)).strip("-")[:100].strip("-")
    return slug or "bai-viet"


def excerpt_of(body: str) -> str:
    """Plain text of the first lines of a Markdown body, for lists."""
    text = re.sub(r"!\[([^\]]*)\]\([^)]*\)", r"\1", body)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"^\s{0,3}(#{1,6}|>|[-*+]|\d+\.)\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"[*_`~]", "", text)
    text = " ".join(text.split())
    return text if len(text) <= EXCERPT_LENGTH else text[: EXCERPT_LENGTH - 1].rstrip() + "…"


async def _unique_slug(db: AsyncSession, tree_id: int, title: str) -> str:
    base = make_slug(title)
    taken = set((await db.execute(select(Article.slug).where(Article.tree_id == tree_id, Article.slug.like(f"{base}%")))).scalars().all())
    if base not in taken:
        return base
    n = 2
    while f"{base}-{n}" in taken:
        n += 1
    return f"{base}-{n}"


async def _cover_url(db: AsyncSession, article: Article) -> str | None:
    if article.cover_media_id is None:
        return None
    media = await db.get(Media, article.cover_media_id)
    if media is None:
        return None
    return f"/uploads/media/thumbs/{media.thumb_name}" if media.thumb_name else f"/uploads/media/{media.stored_name}"


async def _members_of(db: AsyncSession, article_id: int) -> list[MemberName]:
    rows = (
        await db.execute(
            select(Member.id, Member.full_name)
            .join(ArticleMember, ArticleMember.member_id == Member.id)
            .where(ArticleMember.article_id == article_id)
            .order_by(Member.id)
        )
    ).all()
    return [MemberName(id=i, name=n) for i, n in rows]


async def _read(db: AsyncSession, article: Article) -> ArticleRead:
    return ArticleRead(
        id=article.id,
        title=article.title,
        slug=article.slug,
        kind=article.kind,
        body=article.body,
        status=article.status,
        pinned=article.pinned,
        position=article.position,
        cover_url=await _cover_url(db, article),
        cover_media_id=article.cover_media_id,
        members=await _members_of(db, article.id),
        created_at=article.created_at,
        updated_at=article.updated_at,
    )


async def _summary(db: AsyncSession, article: Article) -> ArticleSummary:
    return ArticleSummary(
        id=article.id,
        title=article.title,
        slug=article.slug,
        kind=article.kind,
        excerpt=excerpt_of(article.body),
        status=article.status,
        pinned=article.pinned,
        position=article.position,
        cover_url=await _cover_url(db, article),
        updated_at=article.updated_at,
    )


def _visible(ctx: TreeContext, article: Article | None) -> bool:
    return article is not None and article.tree_id == ctx.tree.id and (article.status == "published" or _is_admin(ctx))


async def _get_visible(db: AsyncSession, ctx: TreeContext, article_id: int) -> Article:
    article = await db.get(Article, article_id)
    if not _visible(ctx, article):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="article not found")
    return article


async def _admin_article(db: AsyncSession, ctx: TreeContext, article_id: int) -> Article:
    article = await db.get(Article, article_id)
    if article is None or article.tree_id != ctx.tree.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="article not found")
    return article


async def _check_members(db: AsyncSession, ctx: TreeContext, member_ids: list[int]) -> list[int]:
    ids = sorted(set(member_ids))
    if ids:
        found = set((await db.execute(select(Member.id).where(Member.tree_id == ctx.tree.id, Member.id.in_(ids)))).scalars().all())
        if found != set(ids):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="member not found")
    return ids


async def _check_cover(db: AsyncSession, article_id: int | None, cover_media_id: int | None) -> None:
    if cover_media_id is None:
        return
    media = await db.get(Media, cover_media_id)
    if article_id is None or media is None or media.article_id != article_id or media.kind != "image":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="cover must be an image of this article")


def _values(article: Article, member_ids: list[int]) -> dict:
    return {
        "title": article.title,
        "kind": article.kind,
        "body": article.body,
        "status": article.status,
        "pinned": article.pinned,
        "cover_media_id": article.cover_media_id,
        "member_ids": member_ids,
    }


async def _set_members(db: AsyncSession, article_id: int, ids: list[int]) -> None:
    await db.execute(delete(ArticleMember).where(ArticleMember.article_id == article_id))
    db.add_all([ArticleMember(article_id=article_id, member_id=i) for i in ids])


ORDER = (Article.pinned.desc(), Article.position, Article.id.desc())


@router.get("/articles", response_model=list[ArticleSummary])
async def list_articles(
    kind: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    ctx: TreeContext = Depends(get_read_context),
) -> list[ArticleSummary]:
    if kind is not None and kind not in ARTICLE_KINDS:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="unknown kind")
    query = select(Article).where(Article.tree_id == ctx.tree.id).order_by(*ORDER)
    if kind is not None:
        query = query.where(Article.kind == kind)
    if not _is_admin(ctx):
        query = query.where(Article.status == "published")
    return [await _summary(db, a) for a in (await db.execute(query)).scalars().all()]


@router.post("/articles/reorder", status_code=status.HTTP_204_NO_CONTENT)
async def reorder_articles(payload: Reorder, db: AsyncSession = Depends(get_db), ctx: TreeContext = Depends(get_write_context)) -> None:
    found = set((await db.execute(select(Article.id).where(Article.tree_id == ctx.tree.id, Article.id.in_(payload.ids)))).scalars().all())
    if found != set(payload.ids):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="article not found")
    for position, article_id in enumerate(payload.ids):
        await db.execute(update(Article).where(Article.id == article_id).values(position=position))
    await db.commit()


@router.get("/articles/by-slug/{slug}", response_model=ArticleRead)
async def get_by_slug(slug: str, db: AsyncSession = Depends(get_db), ctx: TreeContext = Depends(get_read_context)) -> ArticleRead:
    article = (await db.execute(select(Article).where(Article.tree_id == ctx.tree.id, Article.slug == slug))).scalar_one_or_none()
    if not _visible(ctx, article):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="article not found")
    return await _read(db, article)


@router.get("/articles/{article_id}", response_model=ArticleRead)
async def get_article(article_id: int, db: AsyncSession = Depends(get_db), ctx: TreeContext = Depends(get_read_context)) -> ArticleRead:
    return await _read(db, await _get_visible(db, ctx, article_id))


@router.post("/articles", response_model=ArticleRead, status_code=status.HTTP_201_CREATED)
async def create_article(payload: ArticleCreate, db: AsyncSession = Depends(get_db), ctx: TreeContext = Depends(get_write_context)) -> ArticleRead:
    await _check_cover(db, None, payload.cover_media_id)  # a new article has no images yet, so it cannot have a cover
    ids = await _check_members(db, ctx, payload.member_ids)
    article = Article(
        tree_id=ctx.tree.id,
        title=payload.title,
        slug=await _unique_slug(db, ctx.tree.id, payload.title),
        kind=payload.kind,
        body=payload.body,
        status=payload.status,
        pinned=payload.pinned,
        created_by=ctx.user.id,
    )
    db.add(article)
    await db.flush()
    await _set_members(db, article.id, ids)
    audit.record(
        db,
        tree_id=ctx.tree.id,
        actor=ctx.user,
        action="article.create",
        changes={k: [None, v] for k, v in _values(article, ids).items() if v not in (None, False, "", [])},
        details={"article_id": article.id, "title": article.title},
    )
    await db.commit()
    await db.refresh(article)
    return await _read(db, article)


@router.put("/articles/{article_id}", response_model=ArticleRead)
async def update_article(
    article_id: int, payload: ArticleUpdate, db: AsyncSession = Depends(get_db), ctx: TreeContext = Depends(get_write_context)
) -> ArticleRead:
    article = await _admin_article(db, ctx, article_id)
    await _check_cover(db, article.id, payload.cover_media_id)
    ids = await _check_members(db, ctx, payload.member_ids)
    before = _values(article, [m.id for m in await _members_of(db, article.id)])
    article.title, article.kind, article.body = payload.title, payload.kind, payload.body
    article.status, article.pinned, article.cover_media_id = payload.status, payload.pinned, payload.cover_media_id
    await _set_members(db, article.id, ids)
    changes = diff_values(before, _values(article, ids))
    if changes:
        audit.record(
            db, tree_id=ctx.tree.id, actor=ctx.user, action="article.update", changes=changes,
            details={"article_id": article.id, "title": article.title},
        )
    await db.commit()
    await db.refresh(article)
    return await _read(db, article)


@router.delete("/articles/{article_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_article(article_id: int, db: AsyncSession = Depends(get_db), ctx: TreeContext = Depends(get_write_context)) -> None:
    article = await _admin_article(db, ctx, article_id)
    audit.record(
        db,
        tree_id=ctx.tree.id,
        actor=ctx.user,
        action="article.delete",
        changes={"title": [article.title, None], "kind": [article.kind, None], "status": [article.status, None]},
        details={"article_id": article.id, "title": article.title},
    )
    media = list((await db.execute(select(Media).where(Media.article_id == article.id))).scalars().all())
    await db.delete(article)
    await db.commit()
    delete_media_files(media)


@router.get("/members/{member_id}/articles", response_model=list[ArticleSummary])
async def articles_mentioning(member_id: int, db: AsyncSession = Depends(get_db), ctx: TreeContext = Depends(get_read_context)) -> list[ArticleSummary]:
    member = await db.get(Member, member_id)
    if member is None or member.tree_id != ctx.tree.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="member not found")
    query = (
        select(Article)
        .join(ArticleMember, ArticleMember.article_id == Article.id)
        .where(Article.tree_id == ctx.tree.id, ArticleMember.member_id == member_id)
        .order_by(*ORDER)
    )
    if not _is_admin(ctx):
        query = query.where(Article.status == "published")
    return [await _summary(db, a) for a in (await db.execute(query)).scalars().all()]
