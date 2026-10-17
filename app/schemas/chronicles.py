from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

ARTICLE_KINDS = ("origin", "lineage", "precepts", "event", "person", "other")
MAX_BODY = 100_000
MAX_WORDS = 200


def _text(value: str, what: str = "title") -> str:
    value = value.strip()
    if not value:
        raise ValueError(f"{what} must not be empty")
    return value


class ArticleBase(BaseModel):
    title: str = Field(max_length=200)
    kind: Literal["origin", "lineage", "precepts", "event", "person", "other"]
    body: str = Field(default="", max_length=MAX_BODY)
    status: Literal["draft", "published"] = "draft"
    pinned: bool = False
    cover_media_id: int | None = None
    member_ids: list[int] = Field(default_factory=list, max_length=500)

    @field_validator("title")
    @classmethod
    def _title(cls, value: str) -> str:
        return _text(value)


class ArticleCreate(ArticleBase):
    pass


class ArticleUpdate(ArticleBase):
    """PUT replaces the article (the slug and the position are kept)."""


class MemberName(BaseModel):
    id: int
    name: str


class ArticleSummary(BaseModel):
    id: int
    title: str
    slug: str
    kind: str
    excerpt: str
    status: str
    pinned: bool
    position: int
    cover_url: str | None
    updated_at: datetime


class ArticleRead(BaseModel):
    id: int
    title: str
    slug: str
    kind: str
    body: str
    status: str
    pinned: bool
    position: int
    cover_url: str | None
    cover_media_id: int | None
    members: list[MemberName]
    created_at: datetime
    updated_at: datetime


class Reorder(BaseModel):
    ids: list[int] = Field(max_length=1000)


class TimelineBase(BaseModel):
    year: int = Field(ge=1, le=2200)
    month: int | None = Field(default=None, ge=1, le=12)
    day: int | None = Field(default=None, ge=1, le=31)
    title: str = Field(max_length=200)
    body: str | None = Field(default=None, max_length=5000)
    member_id: int | None = None
    article_id: int | None = None

    @field_validator("title")
    @classmethod
    def _title(cls, value: str) -> str:
        return _text(value)

    @field_validator("body", mode="before")
    @classmethod
    def _blank(cls, value: object) -> object:
        return (value.strip() or None) if isinstance(value, str) else value

    @model_validator(mode="after")
    def _check_date(self) -> "TimelineBase":
        if self.day is not None:
            if self.month is None:
                raise ValueError("a day needs its month")
            try:
                date(self.year, self.month, self.day)
            except ValueError:
                raise ValueError("that day does not exist in that month") from None
        return self


class TimelineCreate(TimelineBase):
    pass


class TimelineUpdate(TimelineBase):
    """PUT replaces the entry."""


class TimelineRead(TimelineBase):
    id: int
    member_name: str | None = None


class WordIn(BaseModel):
    generation: int = Field(ge=1, le=200)
    word: str = Field(max_length=60)
    meaning: str | None = Field(default=None, max_length=500)

    @field_validator("word")
    @classmethod
    def _word(cls, value: str) -> str:
        return _text(value, "word")

    @field_validator("meaning", mode="before")
    @classmethod
    def _blank(cls, value: object) -> object:
        return (value.strip() or None) if isinstance(value, str) else value


class WordsIn(BaseModel):
    words: list[WordIn] = Field(max_length=MAX_WORDS)

    @model_validator(mode="after")
    def _unique(self) -> "WordsIn":
        generations = [w.generation for w in self.words]
        if len(generations) != len(set(generations)):
            raise ValueError("each generation may appear once")
        return self


class WordOut(BaseModel):
    generation: int
    word: str
    meaning: str | None
