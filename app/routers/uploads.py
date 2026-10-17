"""Avatar files. They used to be a public static mount; now every image is served only to people who may
read the tree its member belongs to (see `can_read_tree`). Anything else - unknown, orphaned, malformed or
forbidden - is a plain 404 so a stranger learns nothing about which files exist."""

import re
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.media_files import media_dir, thumbs_dir
from app.core.permissions import can_read_tree, read_access
from app.core.privacy import privacy_for
from app.db.session import get_db
from app.models.media import Media
from app.models.member import Member

router = APIRouter(tags=["uploads"])

# What upload_avatar writes: a uuid4 plus the extension of an allowed image type.
AVATAR_NAME = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\.(jpg|png|webp)$")
MEDIA_TYPES = {".jpg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}


@router.get("/uploads/avatars/{filename}")
async def get_avatar(filename: str, request: Request, db: AsyncSession = Depends(get_db)) -> FileResponse:
    not_found = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not found")
    if not AVATAR_NAME.match(filename):
        raise not_found
    tree_id = (
        await db.execute(select(Member.tree_id).where(Member.avatar_url == f"/uploads/avatars/{filename}"))
    ).scalar_one_or_none()
    if tree_id is None:
        raise not_found
    allowed, user = await read_access(request, db, tree_id)
    # the same per-field rule as the member detail: a photo closed to this viewer is closed as a file too
    if not allowed or not (await privacy_for(db, tree_id, user)).can_see("avatar"):
        raise not_found
    path = Path(get_settings().upload_dir, "avatars", filename)
    if not path.is_file():
        raise not_found
    return FileResponse(
        path,
        media_type=MEDIA_TYPES[path.suffix],
        # Names are random and never reused, but a logged-out browser must not keep showing a private photo
        # to the next person at the keyboard for long: private cache only, one hour.
        headers={"Cache-Control": "private, max-age=3600"},
    )


MEDIA_NAME = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\.(jpg|png|webp|pdf)$")


async def _serve_media(request: Request, db: AsyncSession, filename: str, *, thumb: bool) -> FileResponse:
    not_found = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not found")
    if not MEDIA_NAME.match(filename):
        raise not_found
    column = Media.thumb_name if thumb else Media.stored_name
    row = (await db.execute(select(Media).where(column == filename))).scalar_one_or_none()
    # Media is never shown to guests, even on a public tree (scans of documents and graves).
    if row is None or not await can_read_tree(request, db, row.tree_id, allow_guests=False):
        raise not_found
    path = (thumbs_dir() if thumb else media_dir()) / filename
    if not path.is_file():
        raise not_found
    return FileResponse(
        path,
        media_type="image/jpeg" if thumb else row.content_type,
        headers={"Cache-Control": "private, max-age=3600"},
    )


@router.get("/uploads/media/thumbs/{filename}")
async def get_media_thumb(filename: str, request: Request, db: AsyncSession = Depends(get_db)) -> FileResponse:
    return await _serve_media(request, db, filename, thumb=True)


@router.get("/uploads/media/{filename}")
async def get_media(filename: str, request: Request, db: AsyncSession = Depends(get_db)) -> FileResponse:
    return await _serve_media(request, db, filename, thumb=False)
