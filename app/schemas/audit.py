from datetime import datetime
from typing import Any

from pydantic import BaseModel


class AuditEntry(BaseModel):
    id: int
    action: str
    actor_id: int | None
    actor_name: str
    #: the actor's role now ("superadmin" = the platform owner acting inside this family); None when the account was deleted
    actor_role: str | None = None
    member_id: int | None
    member_name: str | None
    changes: dict[str, list[Any]] | None
    details: dict[str, Any] | None
    request_id: int | None
    created_at: datetime


class AuditPage(BaseModel):
    total: int
    items: list[AuditEntry]


class AuditActor(BaseModel):
    id: int
    name: str
    role: str
