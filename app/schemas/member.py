from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class MemberCreate(BaseModel):
    full_name: str = Field(min_length=1)
    parent_id: int | None = None


class MemberUpdate(BaseModel):
    full_name: str = Field(min_length=1)
    parent_id: int | None = None


class MemberRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    full_name: str
    parent_id: int | None
    created_at: datetime


class MemberTreeNode(BaseModel):
    id: int
    name: str
    children: list["MemberTreeNode"] = []
