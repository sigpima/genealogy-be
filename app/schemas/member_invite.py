from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from app.schemas.search import PersonRef


class InviteCreated(BaseModel):
    """The one time the link is shown: only its hash is kept."""

    id: int
    path: str
    expires_at: datetime


class InviteRead(BaseModel):
    id: int
    member: PersonRef
    status: Literal["pending", "used", "expired", "revoked"]
    created_at: datetime
    expires_at: datetime
    used_at: datetime | None = None
    used_by_email: str | None = None
