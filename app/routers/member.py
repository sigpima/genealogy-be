import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.session import get_db
from app.models.marriage import Marriage
from app.models.member import Member
from app.routers.auth import get_current_user
from app.schemas.member import (
    MarriageCreate,
    MarriageUpdate,
    MemberCreate,
    MemberDetail,
    MemberRead,
    MemberSkeletonNode,
    MemberTreeNode,
    MemberUpdate,
    SpouseInfo,
)

ALLOWED_AVATAR_CONTENT_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}
MAX_AVATAR_SIZE = 5 * 1024 * 1024

router = APIRouter(
    prefix="/members", tags=["members"], dependencies=[Depends(get_current_user)]
)


def _delete_avatar_file(upload_dir: str, avatar_url: str | None) -> None:
    if not avatar_url:
        return
    relative_path = avatar_url.removeprefix("/uploads/")
    Path(upload_dir, relative_path).unlink(missing_ok=True)


def _spouse_info(marriage: Marriage, spouse: Member) -> SpouseInfo:
    return SpouseInfo(
        marriage_id=marriage.id,
        marriage_year=marriage.marriage_year,
        id=spouse.id,
        full_name=spouse.full_name,
        birth_year=spouse.birth_year,
        death_year=spouse.death_year,
        gender=spouse.gender,
        notes=spouse.notes,
    )


def _build_tree(members: list[Member], marriages: list[Marriage]) -> MemberTreeNode | None:
    spouse_ids = {marriage.spouse_id for marriage in marriages}
    marriages_by_member: dict[int, list[Marriage]] = {}
    for marriage in marriages:
        marriages_by_member.setdefault(marriage.member_id, []).append(marriage)
    members_by_id = {member.id: member for member in members}

    children_by_parent: dict[int | None, list[Member]] = {}
    for member in members:
        children_by_parent.setdefault(member.parent_id, []).append(member)

    root_candidates = [
        member for member in children_by_parent.get(None, []) if member.id not in spouse_ids
    ]
    if not root_candidates:
        return None
    root = root_candidates[0]

    def build(node: Member) -> MemberTreeNode:
        spouses = [
            _spouse_info(marriage, members_by_id[marriage.spouse_id])
            for marriage in marriages_by_member.get(node.id, [])
        ]
        return MemberTreeNode(
            id=node.id,
            name=node.full_name,
            birth_year=node.birth_year,
            death_year=node.death_year,
            gender=node.gender,
            notes=node.notes,
            avatar_url=node.avatar_url,
            spouses=spouses,
            children=[build(child) for child in children_by_parent.get(node.id, [])],
        )

    return build(root)


def _to_skeleton(node: MemberTreeNode) -> MemberSkeletonNode:
    return MemberSkeletonNode(
        id=node.id,
        name=node.name,
        children=[_to_skeleton(child) for child in node.children],
    )


def _sibling_rank(member: Member, siblings: list[Member]) -> str | None:
    """Trưởng/Thứ/Út among same-gender siblings, ordered by birth year (unknown last), then id.

    `siblings` must include `member` itself. None for a member with no parent or no male/female gender.
    """
    if member.parent_id is None or member.gender not in ("male", "female"):
        return None
    same_gender = sorted(
        (s for s in siblings if s.gender == member.gender),
        key=lambda s: (s.birth_year is None, s.birth_year or 0, s.id),
    )
    position = next((i for i, s in enumerate(same_gender) if s.id == member.id), None)
    if position is None:
        return None
    suffix = "nam" if member.gender == "male" else "nữ"
    if position == 0:
        return f"Trưởng {suffix}"
    if position == len(same_gender) - 1:
        return f"Út {suffix}"
    return f"Thứ {suffix}"


async def _is_descendant(db: AsyncSession, ancestor_id: int, candidate_id: int) -> bool:
    """True if candidate_id is currently a descendant of ancestor_id."""
    current_id: int | None = candidate_id
    while current_id is not None:
        if current_id == ancestor_id:
            return True
        current = await db.get(Member, current_id)
        current_id = current.parent_id if current else None
    return False


@router.get("/tree", response_model=MemberSkeletonNode | None)
async def get_tree(db: AsyncSession = Depends(get_db)) -> MemberSkeletonNode | None:
    members_result = await db.execute(select(Member))
    members = list(members_result.scalars().all())
    marriages_result = await db.execute(select(Marriage))
    marriages = list(marriages_result.scalars().all())
    full_tree = _build_tree(members, marriages)
    return _to_skeleton(full_tree) if full_tree is not None else None


@router.get("/{member_id}", response_model=MemberDetail)
async def get_member_detail(member_id: int, db: AsyncSession = Depends(get_db)) -> MemberDetail:
    member = await db.get(Member, member_id)
    if member is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="member not found")

    marriages_result = await db.execute(select(Marriage).where(Marriage.member_id == member_id))
    marriages = list(marriages_result.scalars().all())
    spouses = []
    for marriage in marriages:
        spouse = await db.get(Member, marriage.spouse_id)
        if spouse is not None:
            spouses.append(_spouse_info(marriage, spouse))

    sibling_rank = None
    if member.parent_id is not None:
        siblings_result = await db.execute(select(Member).where(Member.parent_id == member.parent_id))
        sibling_rank = _sibling_rank(member, list(siblings_result.scalars().all()))

    return MemberDetail(
        id=member.id,
        birth_year=member.birth_year,
        death_year=member.death_year,
        gender=member.gender,
        notes=member.notes,
        avatar_url=member.avatar_url,
        courtesy_name=member.courtesy_name,
        title=member.title,
        residence=member.residence,
        burial_place=member.burial_place,
        burial_latitude=member.burial_latitude,
        burial_longitude=member.burial_longitude,
        sibling_rank=sibling_rank,
        spouses=spouses,
    )


@router.post("", response_model=MemberRead, status_code=status.HTTP_201_CREATED)
async def create_member(payload: MemberCreate, db: AsyncSession = Depends(get_db)) -> Member:
    if payload.parent_id is not None:
        parent = await db.get(Member, payload.parent_id)
        if parent is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="parent not found")

    member = Member(
        full_name=payload.full_name,
        parent_id=payload.parent_id,
        birth_year=payload.birth_year,
        death_year=payload.death_year,
        gender=payload.gender.value if payload.gender is not None else None,
        notes=payload.notes,
        courtesy_name=payload.courtesy_name,
        title=payload.title,
        residence=payload.residence,
        burial_place=payload.burial_place,
        burial_latitude=payload.burial_latitude,
        burial_longitude=payload.burial_longitude,
    )
    db.add(member)
    await db.commit()
    await db.refresh(member)
    return member


@router.put("/{member_id}", response_model=MemberRead)
async def update_member(
    member_id: int, payload: MemberUpdate, db: AsyncSession = Depends(get_db)
) -> Member:
    member = await db.get(Member, member_id)
    if member is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="member not found")

    if payload.parent_id is not None:
        if payload.parent_id == member_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="a member cannot be its own parent",
            )
        new_parent = await db.get(Member, payload.parent_id)
        if new_parent is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="parent not found")
        if await _is_descendant(db, member_id, payload.parent_id):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="cannot set parent to one of the member's own descendants",
            )

    member.full_name = payload.full_name
    member.parent_id = payload.parent_id
    member.birth_year = payload.birth_year
    member.death_year = payload.death_year
    member.gender = payload.gender.value if payload.gender is not None else None
    member.notes = payload.notes
    member.courtesy_name = payload.courtesy_name
    member.title = payload.title
    member.residence = payload.residence
    member.burial_place = payload.burial_place
    member.burial_latitude = payload.burial_latitude
    member.burial_longitude = payload.burial_longitude
    await db.commit()
    await db.refresh(member)
    return member


@router.delete("/{member_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_member(member_id: int, db: AsyncSession = Depends(get_db)) -> None:
    member = await db.get(Member, member_id)
    if member is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="member not found")

    await db.delete(member)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="cannot delete a member who has children",
        )


@router.post(
    "/{member_id}/marriages", response_model=SpouseInfo, status_code=status.HTTP_201_CREATED
)
async def create_marriage(
    member_id: int, payload: MarriageCreate, db: AsyncSession = Depends(get_db)
) -> SpouseInfo:
    member = await db.get(Member, member_id)
    if member is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="member not found")

    spouse = Member(
        full_name=payload.spouse_full_name,
        parent_id=None,
        birth_year=payload.spouse_birth_year,
        death_year=payload.spouse_death_year,
        gender=payload.spouse_gender.value if payload.spouse_gender is not None else None,
        notes=payload.spouse_notes,
    )
    db.add(spouse)
    await db.flush()

    marriage = Marriage(member_id=member_id, spouse_id=spouse.id, marriage_year=payload.marriage_year)
    db.add(marriage)
    await db.commit()
    await db.refresh(spouse)
    await db.refresh(marriage)
    return _spouse_info(marriage, spouse)


@router.put("/marriages/{marriage_id}", response_model=SpouseInfo)
async def update_marriage(
    marriage_id: int, payload: MarriageUpdate, db: AsyncSession = Depends(get_db)
) -> SpouseInfo:
    marriage = await db.get(Marriage, marriage_id)
    if marriage is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="marriage not found")

    spouse = await db.get(Member, marriage.spouse_id)
    marriage.marriage_year = payload.marriage_year
    spouse.full_name = payload.spouse_full_name
    spouse.birth_year = payload.spouse_birth_year
    spouse.death_year = payload.spouse_death_year
    spouse.gender = payload.spouse_gender.value if payload.spouse_gender is not None else None
    spouse.notes = payload.spouse_notes
    await db.commit()
    await db.refresh(spouse)
    await db.refresh(marriage)
    return _spouse_info(marriage, spouse)


@router.post("/{member_id}/avatar")
async def upload_avatar(
    member_id: int, file: UploadFile = File(...), db: AsyncSession = Depends(get_db)
) -> dict[str, str]:
    member = await db.get(Member, member_id)
    if member is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="member not found")

    extension = ALLOWED_AVATAR_CONTENT_TYPES.get(file.content_type or "")
    if extension is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="unsupported image type"
        )

    contents = await file.read()
    if len(contents) > MAX_AVATAR_SIZE:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="file too large")

    settings = get_settings()
    _delete_avatar_file(settings.upload_dir, member.avatar_url)

    avatars_dir = Path(settings.upload_dir) / "avatars"
    avatars_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{uuid.uuid4()}{extension}"
    (avatars_dir / filename).write_bytes(contents)

    avatar_url = f"/uploads/avatars/{filename}"
    member.avatar_url = avatar_url
    await db.commit()
    return {"avatar_url": avatar_url}


@router.delete("/{member_id}/avatar", status_code=status.HTTP_204_NO_CONTENT)
async def delete_avatar(member_id: int, db: AsyncSession = Depends(get_db)) -> None:
    member = await db.get(Member, member_id)
    if member is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="member not found")

    settings = get_settings()
    _delete_avatar_file(settings.upload_dir, member.avatar_url)
    member.avatar_url = None
    await db.commit()
