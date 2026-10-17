"""Where media files live and how they are removed. Names are random UUIDs; originals under media/, thumbnails under
media/thumbs/ (both inside UPLOAD_DIR)."""

from pathlib import Path

from app.core.config import get_settings
from app.models.media import Media


def media_dir() -> Path:
    return Path(get_settings().upload_dir) / "media"


def thumbs_dir() -> Path:
    return media_dir() / "thumbs"


def delete_media_files(rows: list[Media]) -> None:
    for row in rows:
        (media_dir() / row.stored_name).unlink(missing_ok=True)
        if row.thumb_name:
            (thumbs_dir() / row.thumb_name).unlink(missing_ok=True)
