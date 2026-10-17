from datetime import datetime
from typing import Any

from pydantic import BaseModel


class AuditEntry(BaseModel):
    id: int
    action: str
    actor_id: int | None
    actor_name: str
    member_id: int | None
    member_name: str | None
    changes: dict[str, list[Any]] | None
    details: dict[str, Any] | None
    request_id: int | None
    created_at: datetime


class AuditPage(BaseModel):
    total: int
    items: list[AuditEntry]
