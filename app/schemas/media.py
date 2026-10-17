from datetime import datetime

from pydantic import BaseModel, Field, field_validator


class MediaRead(BaseModel):
    id: int
    kind: str
    original_name: str
    content_type: str
    size: int
    width: int | None
    height: int | None
    caption: str | None
    member_id: int | None
    place_id: int | None
    article_id: int | None = None
    url: str
    thumb_url: str | None
    created_at: datetime


class CaptionUpdate(BaseModel):
    caption: str | None = Field(default=None, max_length=2000)

    @field_validator("caption")
    @classmethod
    def _clean(cls, value: str | None) -> str | None:
        value = (value or "").strip()
        return value or None
