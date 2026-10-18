"""Rules about a person that hold on every write path (form, grid, CSV import, approved proposal)."""

from fastapi import HTTPException

from app.models.member import Member


def check_adoption(parent_id: int | None, is_adopted: bool, *, existing: Member | None = None) -> None:
    """A person without a father cannot be adopted ("con nuôi" means adopted by someone).

    An existing row that already is an adopted root is left alone while that state is unchanged, so the
    data entered before this rule can still be edited (the flag can be cleared at any time).
    """
    if not is_adopted or parent_id is not None:
        return
    if existing is not None and existing.is_adopted and existing.parent_id is None:
        return
    raise HTTPException(
        status_code=422,
        detail="a person without a father cannot be adopted",
    )
