"""Checking an uploaded file and making its thumbnail. CPU work: callers run it in a thread.

The declared content type is only a claim: an image must really open as one (Pillow), a PDF must really start with `%PDF-`.
"""

import io
from dataclasses import dataclass

from PIL import Image, ImageOps, UnidentifiedImageError

MAX_BYTES = 10 * 1024 * 1024
THUMB_SIZE = 480
MAX_PIXELS = 60_000_000  # refuse decompression bombs: a tiny file that expands to gigabytes of pixels

IMAGE_TYPES = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}
FORMAT_TO_TYPE = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}
PDF_TYPE = "application/pdf"


class MediaRejected(ValueError):
    """The file is not acceptable; the message is safe to show."""


@dataclass
class Processed:
    kind: str  # image | document
    content_type: str
    extension: str
    width: int | None
    height: int | None
    thumbnail: bytes | None  # JPEG bytes


def process_upload(data: bytes, declared_type: str) -> Processed:
    if not data:
        raise MediaRejected("empty file")
    if len(data) > MAX_BYTES:
        raise MediaRejected("file too large (max 10 MB)")
    if declared_type == PDF_TYPE:
        if not data.startswith(b"%PDF-"):
            raise MediaRejected("not a PDF file")
        return Processed("document", PDF_TYPE, ".pdf", None, None, None)
    if declared_type not in IMAGE_TYPES:
        raise MediaRejected("unsupported file type (JPEG, PNG, WebP or PDF)")
    try:
        with Image.open(io.BytesIO(data)) as probe:
            actual_type = FORMAT_TO_TYPE.get(probe.format or "")
            width, height = probe.size
            if actual_type is None:
                raise MediaRejected("unsupported image format")
            if width * height > MAX_PIXELS:
                raise MediaRejected("image has too many pixels")
            probe.verify()  # catches truncated/corrupt files without decoding everything
        with Image.open(io.BytesIO(data)) as image:
            image = ImageOps.exif_transpose(image)  # a phone photo taken sideways is shown upright
            image.thumbnail((THUMB_SIZE, THUMB_SIZE))
            if image.mode in ("RGBA", "LA", "P"):
                rgba = image.convert("RGBA")
                flat = Image.new("RGB", rgba.size, "white")
                flat.paste(rgba, mask=rgba.split()[-1])
                image = flat
            else:
                image = image.convert("RGB")
            buffer = io.BytesIO()
            image.save(buffer, "JPEG", quality=82, optimize=True)
    except MediaRejected:
        raise
    except (UnidentifiedImageError, OSError, SyntaxError, Image.DecompressionBombError):
        raise MediaRejected("not a valid image") from None
    return Processed("image", actual_type, IMAGE_TYPES[actual_type], width, height, buffer.getvalue())
