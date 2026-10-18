from pydantic import BaseModel

from app.schemas.admin_overview import TodoItem


class PlatformOverview(BaseModel):
    items: list[TodoItem]
    numbers: dict[str, int]
