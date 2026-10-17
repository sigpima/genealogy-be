from pydantic import BaseModel

from app.schemas.branch import BranchRef


class PersonRef(BaseModel):
    id: int
    name: str


class SearchItem(BaseModel):
    id: int
    full_name: str
    generation: int
    gender: str | None
    birth_year: int | None
    death_year: int | None
    hometown: str | None
    parent_name: str | None
    branch: BranchRef | None
    is_spouse: bool = False
    #: For a spouse: the blood member they married (the tree shows that person).
    spouse_of: PersonRef | None = None


class SearchPage(BaseModel):
    total: int
    items: list[SearchItem]
    #: "Did you mean…": close names, only filled when a text query found nothing.
    suggestions: list[SearchItem] = []


class GenerationCount(BaseModel):
    generation: int
    count: int


class GenderCounts(BaseModel):
    male: int = 0
    female: int = 0
    other: int = 0
    unknown: int = 0


class StatusCounts(BaseModel):
    living: int = 0
    deceased: int = 0
    unknown: int = 0


class BranchCount(BaseModel):
    id: int
    name: str
    color: str
    count: int


class Stats(BaseModel):
    total: int
    spouses: int
    by_generation: list[GenerationCount]
    gender: GenderCounts
    status: StatusCounts
    by_branch: list[BranchCount]
    without_branch: int
