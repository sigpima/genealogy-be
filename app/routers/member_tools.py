"""Bulk data-entry tools for tree admins: the paged table, completeness, split, CSV export/import.

Registered BEFORE `member.router` (see app/main.py): `/members/table` etc. must win over `/members/{member_id}`.
Every route is admin-only and acts on the resolved tree, like the other write routes.
"""

import csv
import io
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import Response
from pydantic import BaseModel, ValidationError, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import get_write_context
from app.core.tenancy import TreeContext
from app.db.session import get_db
from app.models.marriage import Marriage
from app.models.member import Member
from app.core.tree_layout import TreeLayout, load_layout
from app.routers.member import _assign, _member_in_tree, member_values
from app.schemas.member import Gender, MemberCreate, MemberRead, MemberUpdate

router = APIRouter(prefix="/members", tags=["member tools"])

MAX_IMPORT_BYTES = 5 * 1024 * 1024
MAX_IMPORT_ROWS = 10_000
MISSING_FIELDS = ("gender", "birth_year", "hometown", "death_year")


# --------------------------------------------------------------------------- table


class TableRow(BaseModel):
    id: int
    full_name: str
    generation: int
    parent_id: int | None
    parent_name: str | None
    has_children: bool
    gender: str | None
    birth_year: int | None
    birth_month: int | None
    birth_day: int | None
    birth_is_lunar: bool
    death_year: int | None
    death_month: int | None
    death_day: int | None
    death_is_lunar: bool
    courtesy_name: str | None
    title: str | None
    hometown: str | None
    residence: str | None
    phone: str | None
    email: str | None
    birth_order: int | None
    is_adopted: bool
    mother_id: int | None


class TablePage(BaseModel):
    total: int
    items: list[TableRow]


def _row(member: Member, layout: TreeLayout) -> TableRow:
    parent = layout.by_id.get(member.parent_id) if member.parent_id is not None else None
    return TableRow(
        generation=layout.generation[member.id],
        parent_name=parent.full_name if parent else None,
        has_children=bool(layout.children.get(member.id)),
        **{name: getattr(member, name) for name in TableRow.model_fields if hasattr(member, name)},
    )


@router.get("/table", response_model=TablePage)
async def members_table(
    q: str | None = None,
    generation: int | None = Query(default=None, ge=1),
    under: int | None = None,
    missing: Annotated[list[Literal["gender", "birth_year", "hometown", "death_year"]] | None, Query()] = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    ctx: TreeContext = Depends(get_write_context),
) -> TablePage:
    if under is not None and await _member_in_tree(db, ctx.tree.id, under) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="member not found")
    layout = await load_layout(db, ctx.tree.id)
    allowed = layout.subtree_ids(under) if under is not None else None
    needle = q.strip().casefold() if q and q.strip() else None

    rows = []
    for member in layout.order:
        if allowed is not None and member.id not in allowed:
            continue
        if generation is not None and layout.generation[member.id] != generation:
            continue
        if needle is not None and needle not in member.full_name.casefold():
            continue
        if missing and any(getattr(member, field) is not None for field in missing):
            continue  # "missing X" means X is empty; several chips all have to be empty
        rows.append(member)
    return TablePage(total=len(rows), items=[_row(m, layout) for m in rows[offset : offset + limit]])


# --------------------------------------------------------------------------- completeness


class Completeness(BaseModel):
    total: int
    with_gender: int
    with_birth_year: int
    with_hometown: int
    basic: int  # gender and birth year both known


@router.get("/completeness", response_model=Completeness)
async def completeness(
    db: AsyncSession = Depends(get_db), ctx: TreeContext = Depends(get_write_context)
) -> Completeness:
    layout = await load_layout(db, ctx.tree.id)
    members = layout.order
    return Completeness(
        total=len(members),
        with_gender=sum(m.gender is not None for m in members),
        with_birth_year=sum(m.birth_year is not None for m in members),
        with_hometown=sum(m.hometown is not None for m in members),
        basic=sum(m.gender is not None and m.birth_year is not None for m in members),
    )


# --------------------------------------------------------------------------- split


class SplitPayload(BaseModel):
    names: list[str]

    @field_validator("names")
    @classmethod
    def _clean(cls, names: list[str]) -> list[str]:
        cleaned = [name.strip() for name in names]
        if not 2 <= len(cleaned) <= 50:
            raise ValueError("give between 2 and 50 names")
        if any(not name for name in cleaned):
            raise ValueError("names cannot be blank")
        return cleaned


@router.post("/{member_id}/split", response_model=list[MemberRead], status_code=status.HTTP_201_CREATED)
async def split_member(
    member_id: int,
    payload: SplitPayload,
    db: AsyncSession = Depends(get_db),
    ctx: TreeContext = Depends(get_write_context),
) -> list[Member]:
    """Turn one entry such as "Vô Danh 3 Vị" into several siblings: the first name renames the original, the
    others are new members with the same parent, mother and gender (and the original's other facts)."""
    member = await _member_in_tree(db, ctx.tree.id, member_id)
    if member is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="member not found")
    has_child = (await db.execute(select(Member.id).where(Member.parent_id == member_id).limit(1))).first()
    has_spouse = (await db.execute(select(Marriage.id).where(Marriage.member_id == member_id).limit(1))).first()
    if has_child or has_spouse:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="cannot split a member who has children or a spouse",
        )

    template = member_values(member)
    member.full_name = payload.names[0]
    created = [member]
    for name in payload.names[1:]:
        sibling = Member(tree_id=ctx.tree.id, **{**template, "full_name": name})
        db.add(sibling)
        created.append(sibling)
    await db.commit()
    for item in created:
        await db.refresh(item)
    return created


# --------------------------------------------------------------------------- CSV

CSV_COLUMNS = (
    "id", "full_name", "parent_id", "mother_id", "gender", "birth_order", "is_adopted",
    "birth_year", "birth_month", "birth_day", "birth_is_lunar", "birth_leap_month",
    "death_year", "death_month", "death_day", "death_is_lunar", "death_leap_month",
    "courtesy_name", "title", "hometown", "residence", "phone", "email",
    "burial_place", "burial_latitude", "burial_longitude", "notes",
)
INT_COLUMNS = {
    "id", "parent_id", "mother_id", "birth_order", "birth_year", "birth_month", "birth_day",
    "death_year", "death_month", "death_day",
}
BOOL_COLUMNS = {"is_adopted", "birth_is_lunar", "birth_leap_month", "death_is_lunar", "death_leap_month"}
FLOAT_COLUMNS = {"burial_latitude", "burial_longitude"}
BOOL_DEFAULTS = {"is_adopted": False, "birth_is_lunar": False, "birth_leap_month": False,
                 "death_is_lunar": True, "death_leap_month": False}
GENDER_WORDS = {
    "nam": "male", "male": "male", "m": "male",
    "nữ": "female", "nu": "female", "female": "female", "f": "female",
    "khác": "other", "khac": "other", "other": "other",
}
TRUE_WORDS = {"x", "1", "true", "có", "co", "yes", "y"}
FALSE_WORDS = {"0", "false", "không", "khong", "no", "n"}
GENDER_LABELS = {"male": "nam", "female": "nữ", "other": "khác"}


def _export_cell(member: Member, column: str) -> str:
    value = getattr(member, column)
    if value is None:
        return ""
    if column == "gender":
        return GENDER_LABELS.get(value, value)
    if column in BOOL_COLUMNS:
        return "1" if value else "0"
    return str(value)


@router.get("/export.csv")
async def export_csv(
    db: AsyncSession = Depends(get_db), ctx: TreeContext = Depends(get_write_context)
) -> Response:
    layout = await load_layout(db, ctx.tree.id)
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\r\n")
    writer.writerow(CSV_COLUMNS)
    for member in layout.order:
        writer.writerow([_export_cell(member, column) for column in CSV_COLUMNS])
    # BOM so Excel opens the file as UTF-8 (Vietnamese diacritics survive).
    return Response(
        content="﻿" + buffer.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="gia-pha.csv"'},
    )


class _CellError(ValueError):
    pass


def _parse_cell(column: str, raw: str) -> object:
    """One non-blank cell -> a value. '-' clears (None, or the default for flags)."""
    if raw == "-":
        return BOOL_DEFAULTS[column] if column in BOOL_COLUMNS else None
    if column in INT_COLUMNS:
        try:
            return int(raw)
        except ValueError:
            raise _CellError(f"{column}: '{raw}' is not a whole number") from None
    if column in FLOAT_COLUMNS:
        try:
            return float(raw.replace(",", "."))
        except ValueError:
            raise _CellError(f"{column}: '{raw}' is not a number") from None
    if column in BOOL_COLUMNS:
        word = raw.casefold()
        if word in TRUE_WORDS:
            return True
        if word in FALSE_WORDS:
            return False
        raise _CellError(f"{column}: use 1/0, x, true/false or có/không")
    if column == "gender":
        gender = GENDER_WORDS.get(raw.casefold())
        if gender is None:
            raise _CellError("gender: use nam, nữ or khác")
        return gender
    return raw


class ImportResult(BaseModel):
    dry_run: bool
    created: int
    updated: int
    unchanged: int


@router.post("/import", response_model=ImportResult)
async def import_csv(
    file: UploadFile = File(...),
    dry_run: bool = False,
    db: AsyncSession = Depends(get_db),
    ctx: TreeContext = Depends(get_write_context),
) -> ImportResult:
    """Apply a CSV (see export). A row with `id` updates that member, a row without creates a child of
    `parent_id`. Blank cell = unchanged, '-' = clear. All or nothing: any bad row rejects the whole file."""
    raw = await file.read(MAX_IMPORT_BYTES + 1)
    if len(raw) > MAX_IMPORT_BYTES:
        raise HTTPException(status_code=413, detail="file too large (max 5 MB)")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="the file must be UTF-8") from None

    reader = csv.DictReader(io.StringIO(text))
    header = [name.strip() for name in (reader.fieldnames or [])]
    reader.fieldnames = header
    unknown = [name for name in header if name not in CSV_COLUMNS]
    if not header or unknown:
        raise _import_errors([{"row": 1, "message": f"unknown column(s): {', '.join(unknown) or '(no header)'}"}])
    rows = list(reader)
    if len(rows) > MAX_IMPORT_ROWS:
        raise HTTPException(status_code=413, detail="too many rows (max 10,000)")

    tree_members = {
        m.id: m for m in (await db.execute(select(Member).where(Member.tree_id == ctx.tree.id))).scalars().all()
    }
    spouse_pairs = set(
        (
            await db.execute(
                select(Marriage.member_id, Marriage.spouse_id).where(Marriage.member_id.in_(list(tree_members)))
            )
        ).all()
    )
    parent_of = {m.id: m.parent_id for m in tree_members.values()}  # evolves row by row, to catch cycles

    errors: list[dict] = []
    plan: list[tuple[Member | None, MemberUpdate]] = []
    seen_ids: set[int] = set()
    created = updated = unchanged = 0

    for number, record in enumerate(rows, start=2):  # row 1 is the header
        def fail(message: str, number: int = number) -> None:
            errors.append({"row": number, "message": message})

        cells = {k: (v or "").strip() for k, v in record.items() if k is not None}
        try:
            changes = {column: _parse_cell(column, cell) for column, cell in cells.items() if cell}
        except _CellError as exc:
            fail(str(exc))
            continue

        member_id = changes.pop("id", None)
        if member_id is not None:
            member = tree_members.get(member_id)
            if member is None:
                fail(f"id {member_id} is not a member of this tree")
                continue
            if member_id in seen_ids:
                fail(f"id {member_id} appears more than once")
                continue
            seen_ids.add(member_id)
            merged = {**member_values(member), **changes}
        else:
            member = None
            merged = changes

        try:
            payload = MemberUpdate.model_validate(merged)
        except ValidationError as exc:
            for problem in exc.errors():
                where = ".".join(str(p) for p in problem["loc"])
                fail(f"{where + ': ' if where else ''}{problem['msg'].removeprefix('Value error, ')}")
            continue

        parent_id = payload.parent_id
        if member is None and parent_id is None:
            fail("a new member needs parent_id (an existing member)")
            continue
        if parent_id is not None:
            if parent_id not in tree_members:
                fail(f"parent_id {parent_id} is not a member of this tree")
                continue
            if member is not None:
                cursor, cyclic = parent_id, False
                while cursor is not None:
                    if cursor == member.id:
                        cyclic = True
                        break
                    cursor = parent_of.get(cursor)
                if cyclic:
                    fail("parent_id would make the member their own ancestor")
                    continue
        if payload.mother_id is not None and (parent_id, payload.mother_id) not in spouse_pairs:
            fail("mother_id must be a recorded spouse of the father (parent_id)")
            continue

        if member is None:
            created += 1
        elif payload == MemberUpdate.model_validate(member_values(member)):
            unchanged += 1
            continue
        else:
            updated += 1
            parent_of[member.id] = parent_id
        plan.append((member, payload))

    if errors:
        raise _import_errors(errors)
    if not dry_run:
        for member, payload in plan:
            target = member if member is not None else Member(tree_id=ctx.tree.id)
            _assign(target, payload)
            if member is None:
                db.add(target)
        await db.commit()
    return ImportResult(dry_run=dry_run, created=created, updated=updated, unchanged=unchanged)


def _import_errors(errors: list[dict]) -> HTTPException:
    return HTTPException(
        status_code=422,
        detail={"message": f"{len(errors)} problem(s); nothing was imported", "errors": errors[:200]},
    )
