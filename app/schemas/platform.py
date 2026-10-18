from datetime import datetime
from typing import Any

from pydantic import BaseModel

from app.schemas.admin_overview import TodoItem


class PlatformOverview(BaseModel):
    items: list[TodoItem]
    numbers: dict[str, int]


class PlatformEventRead(BaseModel):
    id: int
    action: str
    actor_name: str
    tree_id: int | None
    tree_name: str | None
    details: dict[str, Any] | None
    created_at: datetime


class PlatformEventPage(BaseModel):
    total: int
    items: list[PlatformEventRead]
