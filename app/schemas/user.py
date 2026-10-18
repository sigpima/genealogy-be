from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr

from app.schemas.search import PersonRef


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: EmailStr
    full_name: str
    role: str
    status: str
    tree_id: int | None = None
    tree_name: str | None = None
    #: the person of the tree this account is (set by an invitation link or by an admin), or null
    member: PersonRef | None = None
    created_at: datetime
