from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.member import Member
from app.routers.auth import get_current_user
from app.schemas.member import MemberCreate, MemberRead, MemberTreeNode, MemberUpdate

router = APIRouter(
    prefix="/members", tags=["members"], dependencies=[Depends(get_current_user)]
)


def _build_tree(members: list[Member]) -> MemberTreeNode | None:
    children_by_parent: dict[int | None, list[Member]] = {}
    for member in members:
        children_by_parent.setdefault(member.parent_id, []).append(member)

    root_candidates = children_by_parent.get(None, [])
    if not root_candidates:
        return None
    root = root_candidates[0]

    def build(node: Member) -> MemberTreeNode:
        return MemberTreeNode(
            id=node.id,
            name=node.full_name,
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
    result = await db.execute(select(Member))
    members = list(result.scalars().all())
    return _build_tree(members)


@router.post("", response_model=MemberRead, status_code=status.HTTP_201_CREATED)
async def create_member(payload: MemberCreate, db: AsyncSession = Depends(get_db)) -> Member:
    if payload.parent_id is not None:
        parent = await db.get(Member, payload.parent_id)
        if parent is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="parent not found")

    member = Member(full_name=payload.full_name, parent_id=payload.parent_id)
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
