from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    full_name: str = Field(min_length=1)
    #: only read for the very first registration, and only when BOOTSTRAP_CODE is configured
    bootstrap_code: str | None = None


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: EmailStr
    full_name: str
    role: str
    status: str
    tree_id: int | None = None
    tree_name: str | None = None
    created_at: datetime
