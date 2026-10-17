"""Places of the family (nhà thờ, từ đường, lăng mộ, nghĩa trang, đền) and who rests where.

A grave's location is burial information, which guests of a public tree never get (see MemberDetail's redaction), so every
read here needs a signed-in user of the tree; writes are admin-only."""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.core.audit import diff_values
from app.core.media_files import delete_media_files
from app.core.permissions import get_user_context, get_write_context
from app.core.tenancy import TreeContext
from app.core.text import fold
from app.db.session import get_db
from app.models.media import Media
from app.models.member import Member
from app.models.place import Place
from app.schemas.place import (
    MigrationGroup,
    MigrationResult,
    PlaceCreate,
    PlaceDetail,
    PlaceRead,
    PlaceUpdate,
    Resident,
)

router = APIRouter(prefix="/places", tags=["places"])

FIELDS = ("kind", "name", "address", "latitude", "longitude", "description", "caretaker", "visit_notes")


def _values(place: Place) -> dict:
    return {name: getattr(place, name) for name in FIELDS}


async def _in_tree(db: AsyncSession, ctx: TreeContext, place_id: int) -> Place:
    place = await db.get(Place, place_id)
    if place is None or place.tree_id != ctx.tree.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="place not found")
    return place


async def _counts(db: AsyncSession, ctx: TreeContext) -> tuple[dict[int, int], dict[int, int]]:
    resting = dict(
        (
            await db.execute(
                select(Member.burial_place_id, func.count())
                .where(Member.tree_id == ctx.tree.id, Member.burial_place_id.is_not(None))
                .group_by(Member.burial_place_id)
            )
        ).all()
    )
    media = dict(
        (
            await db.execute(
                select(Media.place_id, func.count())
                .where(Media.tree_id == ctx.tree.id, Media.place_id.is_not(None))
                .group_by(Media.place_id)
            )
        ).all()
    )
    return resting, media


def _read(place: Place, resting: dict[int, int], media: dict[int, int]) -> PlaceRead:
    return PlaceRead(
        id=place.id,
        resting_count=resting.get(place.id, 0),
        media_count=media.get(place.id, 0),
        created_at=place.created_at,
        **_values(place),
    )


@router.get("", response_model=list[PlaceRead])
async def list_places(db: AsyncSession = Depends(get_db), ctx: TreeContext = Depends(get_user_context)) -> list[PlaceRead]:
    places = (await db.execute(select(Place).where(Place.tree_id == ctx.tree.id).order_by(Place.id))).scalars().all()
    resting, media = await _counts(db, ctx)
    return [_read(p, resting, media) for p in places]


@router.post("", response_model=PlaceRead, status_code=status.HTTP_201_CREATED)
async def create_place(payload: PlaceCreate, db: AsyncSession = Depends(get_db), ctx: TreeContext = Depends(get_write_context)) -> PlaceRead:
    place = Place(tree_id=ctx.tree.id, **payload.model_dump())
    db.add(place)
    await db.flush()
    audit.record(
        db,
        tree_id=ctx.tree.id,
        actor=ctx.user,
        action="place.create",
        changes={k: [None, v] for k, v in _values(place).items() if v is not None},
        details={"place_id": place.id, "name": place.name},
    )
    await db.commit()
    await db.refresh(place)
    return _read(place, {}, {})


@router.get("/{place_id}", response_model=PlaceDetail)
async def get_place(place_id: int, db: AsyncSession = Depends(get_db), ctx: TreeContext = Depends(get_user_context)) -> PlaceDetail:
    place = await _in_tree(db, ctx, place_id)
    residents = (
        await db.execute(select(Member).where(Member.tree_id == ctx.tree.id, Member.burial_place_id == place.id).order_by(Member.id))
    ).scalars().all()
    resting, media = await _counts(db, ctx)
    return PlaceDetail(
        **_read(place, resting, media).model_dump(),
        residents=[
            Resident(id=m.id, full_name=m.full_name, plot=m.burial_plot, birth_year=m.birth_year, death_year=m.death_year)
            for m in residents
        ],
    )


@router.put("/{place_id}", response_model=PlaceRead)
async def update_place(
    place_id: int, payload: PlaceUpdate, db: AsyncSession = Depends(get_db), ctx: TreeContext = Depends(get_write_context)
) -> PlaceRead:
    place = await _in_tree(db, ctx, place_id)
    before = _values(place)
    for name, value in payload.model_dump().items():
        setattr(place, name, value)
    changes = diff_values(before, _values(place))
    if changes:
        audit.record(
            db, tree_id=ctx.tree.id, actor=ctx.user, action="place.update", changes=changes,
            details={"place_id": place.id, "name": place.name},
        )
    await db.commit()
    await db.refresh(place)
    resting, media = await _counts(db, ctx)
    return _read(place, resting, media)


@router.delete("/{place_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_place(place_id: int, db: AsyncSession = Depends(get_db), ctx: TreeContext = Depends(get_write_context)) -> None:
    """People keep their `burial_plot` text and lose only the link (FK `SET NULL`); the place's own photos go with it."""
    place = await _in_tree(db, ctx, place_id)
    audit.record(
        db,
        tree_id=ctx.tree.id,
        actor=ctx.user,
        action="place.delete",
        changes={k: [v, None] for k, v in _values(place).items() if v is not None},
        details={"place_id": place.id, "name": place.name},
    )
    media = list((await db.execute(select(Media).where(Media.place_id == place.id))).scalars().all())
    await db.delete(place)
    await db.commit()
    delete_media_files(media)


# --------------------------------------------------------------------------- migrating the old free-text field


def _key(text: str) -> str:
    return fold(text)


@router.post("/migrate-burials", response_model=MigrationResult)
async def migrate_burials(
    dry_run: bool = Query(default=False), db: AsyncSession = Depends(get_db), ctx: TreeContext = Depends(get_write_context)
) -> MigrationResult:
    """Turn the old `burial_place` text into places: one per distinct text (ignoring case, diacritics and spacing), reusing a
    place that already has that name, with the GPS of the first person who has coordinates. Idempotent (anyone already linked
    is skipped) and the old text is left in place. `dry_run=true` only reports."""
    people = (
        await db.execute(
            select(Member)
            .where(Member.tree_id == ctx.tree.id, Member.burial_place_id.is_(None), Member.burial_place.is_not(None))
            .order_by(Member.id)
        )
    ).scalars().all()
    groups: dict[str, list[Member]] = {}
    for person in people:
        if _key(person.burial_place or ""):
            groups.setdefault(_key(person.burial_place), []).append(person)
    existing = {
        _key(p.name): p
        for p in (await db.execute(select(Place).where(Place.tree_id == ctx.tree.id).order_by(Place.id))).scalars().all()
    }
    report, created, linked = [], 0, 0
    for key, members in groups.items():
        first = members[0]
        name = " ".join(first.burial_place.split())[:150]
        with_gps = next((m for m in members if m.burial_latitude is not None and m.burial_longitude is not None), None)
        place = existing.get(key)
        report.append(
            MigrationGroup(
                name=place.name if place else name,
                count=len(members),
                latitude=with_gps.burial_latitude if with_gps else None,
                longitude=with_gps.burial_longitude if with_gps else None,
                existing=place is not None,
            )
        )
        linked += len(members)
        if place is None:
            created += 1
        if dry_run:
            continue
        if place is None:
            place = Place(
                tree_id=ctx.tree.id,
                kind="tomb",
                name=name,
                latitude=with_gps.burial_latitude if with_gps else None,
                longitude=with_gps.burial_longitude if with_gps else None,
            )
            db.add(place)
            await db.flush()
            audit.record(
                db, tree_id=ctx.tree.id, actor=ctx.user, action="place.create",
                changes={"name": [None, place.name], "kind": [None, "tomb"]}, details={"place_id": place.id, "name": place.name, "via": "migrate"},
            )
        await db.execute(update(Member).where(Member.id.in_([m.id for m in members])).values(burial_place_id=place.id))
    if not dry_run and linked:
        audit.record(
            db, tree_id=ctx.tree.id, actor=ctx.user, action="place.migrate", details={"created": created, "linked": linked}
        )
    if not dry_run:
        await db.commit()
    return MigrationResult(dry_run=dry_run, groups=report, created=created, linked=linked)


