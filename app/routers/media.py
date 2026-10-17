"""Photos and scanned documents on people and places ("tư liệu & bút tích"). Admins upload; signed-in users of the tree view
(never guests of a public tree: see the GĐ6 design). Files are served by app/routers/uploads.py with the same checks."""

import asyncio
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.core.media_files import delete_media_files, media_dir, thumbs_dir
from app.core.media_processing import MAX_BYTES, MediaRejected, process_upload
from app.core.permissions import get_user_context, get_write_context
from app.core.tenancy import TreeContext
from app.db.session import get_db
from app.models.article import Article
from app.models.media import Media
from app.models.member import Member
from app.models.place import Place
from app.schemas.media import CaptionUpdate, MediaRead

router = APIRouter(tags=["media"])


def _read(row: Media) -> MediaRead:
    return MediaRead(
        id=row.id,
        kind=row.kind,
        original_name=row.original_name,
        content_type=row.content_type,
        size=row.size,
        width=row.width,
        height=row.height,
        caption=row.caption,
        member_id=row.member_id,
        place_id=row.place_id,
        article_id=row.article_id,
        url=f"/uploads/media/{row.stored_name}",
        thumb_url=f"/uploads/media/thumbs/{row.thumb_name}" if row.thumb_name else None,
        created_at=row.created_at,
    )


OWNER_MODELS = {"member": Member, "place": Place, "article": Article}
OWNER_COLUMNS = {"member": Media.member_id, "place": Media.place_id, "article": Media.article_id}


async def _owner(db: AsyncSession, ctx: TreeContext, kind: str, owner_id: int) -> Member | Place | Article:
    row = await db.get(OWNER_MODELS[kind], owner_id)
    if row is None or row.tree_id != ctx.tree.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"{kind} not found")
    return row


async def _list(db: AsyncSession, ctx: TreeContext, kind: str, owner_id: int) -> list[MediaRead]:
    await _owner(db, ctx, kind, owner_id)
    column = OWNER_COLUMNS[kind]
    rows = (await db.execute(select(Media).where(Media.tree_id == ctx.tree.id, column == owner_id).order_by(Media.id))).scalars().all()
    return [_read(r) for r in rows]


async def _upload(db: AsyncSession, ctx: TreeContext, kind: str, owner_id: int, file: UploadFile, caption: str | None) -> MediaRead:
    owner = await _owner(db, ctx, kind, owner_id)
    data = await file.read(MAX_BYTES + 1)
    try:
        processed = await asyncio.to_thread(process_upload, data, file.content_type or "")
    except MediaRejected as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from None

    stored = f"{uuid.uuid4()}{processed.extension}"
    thumb = f"{uuid.uuid4()}.jpg" if processed.thumbnail else None
    media_dir().mkdir(parents=True, exist_ok=True)
    (media_dir() / stored).write_bytes(data)
    if thumb:
        thumbs_dir().mkdir(parents=True, exist_ok=True)
        (thumbs_dir() / thumb).write_bytes(processed.thumbnail)
    row = Media(
        tree_id=ctx.tree.id,
        member_id=owner.id if kind == "member" else None,
        place_id=owner.id if kind == "place" else None,
        article_id=owner.id if kind == "article" else None,
        kind=processed.kind,
        original_name=(file.filename or "file")[:255],
        content_type=processed.content_type,
        size=len(data),
        width=processed.width,
        height=processed.height,
        stored_name=stored,
        thumb_name=thumb,
        caption=(caption or "").strip() or None,
        uploaded_by=ctx.user.id,
    )
    db.add(row)
    await db.flush()
    _audit(db, ctx, "media.upload", row, owner, kind, {"caption": [None, row.caption]} if row.caption else None)
    try:
        await db.commit()
    except Exception:
        delete_media_files([row])  # do not leave files behind for a row that was never saved
        raise
    await db.refresh(row)
    return _read(row)


def _audit(db: AsyncSession, ctx: TreeContext, action: str, row: Media, owner: Member | Place | Article, kind: str, changes: dict | None) -> None:
    audit.record(
        db,
        tree_id=ctx.tree.id,
        actor=ctx.user,
        action=action,
        member_id=owner.id if kind == "member" else None,
        member_name=owner.full_name if kind == "member" else None,
        changes=changes,
        details={
            "media_id": row.id,
            "original_name": row.original_name,
            "kind": row.kind,
            **({"place_id": owner.id, "place_name": owner.name} if kind == "place" else {}),
            **({"article_id": owner.id, "article_title": owner.title} if kind == "article" else {}),
        },
    )


@router.get("/members/{member_id}/media", response_model=list[MediaRead])
async def list_member_media(member_id: int, db: AsyncSession = Depends(get_db), ctx: TreeContext = Depends(get_user_context)) -> list[MediaRead]:
    return await _list(db, ctx, "member", member_id)


@router.post("/members/{member_id}/media", response_model=MediaRead, status_code=status.HTTP_201_CREATED)
async def upload_member_media(
    member_id: int,
    file: UploadFile = File(...),
    caption: str | None = Form(default=None),
    db: AsyncSession = Depends(get_db),
    ctx: TreeContext = Depends(get_write_context),
) -> MediaRead:
    return await _upload(db, ctx, "member", member_id, file, caption)


@router.get("/places/{place_id}/media", response_model=list[MediaRead])
async def list_place_media(place_id: int, db: AsyncSession = Depends(get_db), ctx: TreeContext = Depends(get_user_context)) -> list[MediaRead]:
    return await _list(db, ctx, "place", place_id)


@router.post("/places/{place_id}/media", response_model=MediaRead, status_code=status.HTTP_201_CREATED)
async def upload_place_media(
    place_id: int,
    file: UploadFile = File(...),
    caption: str | None = Form(default=None),
    db: AsyncSession = Depends(get_db),
    ctx: TreeContext = Depends(get_write_context),
) -> MediaRead:
    return await _upload(db, ctx, "place", place_id, file, caption)


async def _row_in_tree(db: AsyncSession, ctx: TreeContext, media_id: int) -> tuple[Media, Member | Place | Article, str]:
    row = await db.get(Media, media_id)
    if row is None or row.tree_id != ctx.tree.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="media not found")
    kind = "member" if row.member_id is not None else "place" if row.place_id is not None else "article"
    owner = await db.get(OWNER_MODELS[kind], row.member_id or row.place_id or row.article_id)
    return row, owner, kind


@router.get("/articles/{article_id}/media", response_model=list[MediaRead])
async def list_article_media(article_id: int, db: AsyncSession = Depends(get_db), ctx: TreeContext = Depends(get_user_context)) -> list[MediaRead]:
    return await _list(db, ctx, "article", article_id)


@router.post("/articles/{article_id}/media", response_model=MediaRead, status_code=status.HTTP_201_CREATED)
async def upload_article_media(
    article_id: int,
    file: UploadFile = File(...),
    caption: str | None = Form(default=None),
    db: AsyncSession = Depends(get_db),
    ctx: TreeContext = Depends(get_write_context),
) -> MediaRead:
    return await _upload(db, ctx, "article", article_id, file, caption)


@router.patch("/media/{media_id}", response_model=MediaRead)
async def update_caption(
    media_id: int, payload: CaptionUpdate, db: AsyncSession = Depends(get_db), ctx: TreeContext = Depends(get_write_context)
) -> MediaRead:
    row, owner, kind = await _row_in_tree(db, ctx, media_id)
    if payload.caption != row.caption:
        _audit(db, ctx, "media.update", row, owner, kind, {"caption": [row.caption, payload.caption]})
        row.caption = payload.caption
    await db.commit()
    await db.refresh(row)
    return _read(row)


@router.delete("/media/{media_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_media(media_id: int, db: AsyncSession = Depends(get_db), ctx: TreeContext = Depends(get_write_context)) -> None:
    row, owner, kind = await _row_in_tree(db, ctx, media_id)
    _audit(db, ctx, "media.delete", row, owner, kind, None)
    await db.delete(row)
    await db.commit()
    delete_media_files([row])
