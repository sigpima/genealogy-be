from typing import Literal

from pydantic import BaseModel


class TodoItem(BaseModel):
    key: str
    count: int
    text: str
    href: str
    kind: Literal["task", "notice"]


class Overview(BaseModel):
    items: list[TodoItem]
    counts: dict[str, int]
