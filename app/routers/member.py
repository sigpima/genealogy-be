from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.marriage import Marriage
from app.models.member import Member
from app.routers.auth import get_current_user
from app.schemas.member import (
    MarriageCreate,
    MarriageUpdate,
    MemberCreate,
    MemberRead,
    MemberTreeNode,
    MemberUpdate,
    SpouseInfo,
)

router = APIRouter(
    prefix="/members", tags=["members"], dependencies=[Depends(get_current_user)]
)


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
            spouses=spouses,
            children=[build(child) for child in children_by_parent.get(node.id, [])],
        )

    return build(root)


async def _is_descendant(db: AsyncSession, ancestor_id: int, candidate_id: int) -> bool:
    """True if candidate_id is currently a descendant of ancestor_id."""
    current_id: int | None = candidate_id
    while current_id is not None:
        if current_id == ancestor_id:
            return True
        current = await db.get(Member, current_id)
        current_id = current.parent_id if current else None
    return False


@router.get("/tree", response_model=MemberTreeNode | None)
async def get_tree(db: AsyncSession = Depends(get_db)) -> MemberTreeNode | None:
    members_result = await db.execute(select(Member))
    members = list(members_result.scalars().all())
    marriages_result = await db.execute(select(Marriage))
    marriages = list(marriages_result.scalars().all())
    return _build_tree(members, marriages)


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
