from typing import Literal

from pydantic import BaseModel


class FindingRead(BaseModel):
    kind: str
    severity: Literal["warning", "info"]
    member_id: int | None
    member_name: str | None
    message: str


class DataHealth(BaseModel):
    findings: list[FindingRead]
    counts: dict[str, int]
