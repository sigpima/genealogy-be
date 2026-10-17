import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.session import get_db
from app.models.marriage import Marriage
from app.models.member import Member
from app.core.permissions import get_read_context, get_write_context
from app.core.tenancy import TreeContext
from app.core.tree_layout import deepest_branch, load_branches
from app.schemas.branch import BranchRef
from app.schemas.member import (
    MarriageCreate,
    MarriageUpdate,
    MemberCreate,
    MemberDetail,
    MemberPatch,
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

# Every route acts on ONE tree (see app/core/tenancy.py) and never touches another: a member id from
# another tree answers 404, exactly like an id that does not exist. Reads take `get_read_context`
# (an active user, or a guest on a public tree); every write takes `get_write_context` (an admin or
# superadmin) - a new write route that forgets it would be open to members, so tests/test_roles_admin.py
# ::test_members_can_read_but_not_write lists them.
router = APIRouter(prefix="/members", tags=["members"])


def _delete_avatar_file(upload_dir: str, avatar_url: str | None) -> None:
    if not avatar_url:
        return
    relative_path = avatar_url.removeprefix("/uploads/")
    Path(upload_dir, relative_path).unlink(missing_ok=True)


# Everything an admin may write on a member besides the name/parent/gender handled by `_assign`.
PROFILE_FIELDS = (
    "birth_year", "death_year", "notes", "courtesy_name", "title", "residence", "hometown",
    "phone", "email", "burial_place", "burial_latitude", "burial_longitude",
    "birth_month", "birth_day", "death_month", "death_day",
    "birth_is_lunar", "birth_leap_month", "death_is_lunar", "death_leap_month",
    "birth_order", "is_adopted",
)


WRITABLE_FIELDS = ("full_name", "parent_id", "mother_id", "gender", *PROFILE_FIELDS)


def member_values(member: Member) -> dict:
    """The member's writable fields as a `MemberUpdate`-shaped dict (used to merge PATCH and CSV rows)."""
    return {field: getattr(member, field) for field in WRITABLE_FIELDS}


def _assign(member: Member, payload: MemberCreate | MemberUpdate) -> None:
    """Copy every writable field of the payload onto the member (full replacement: omitted -> default)."""
    member.full_name = payload.full_name
    member.parent_id = payload.parent_id
    member.mother_id = payload.mother_id
    member.gender = payload.gender.value if payload.gender is not None else None
    for field in PROFILE_FIELDS:
        setattr(member, field, getattr(payload, field))


async def _check_mother(db: AsyncSession, father_id: int | None, mother_id: int | None) -> None:
    """A mother is only meaningful as one of the father's recorded spouses (a tree has no free-standing mothers)."""
    if mother_id is None:
        return
    if father_id is not None:
        result = await db.execute(
            select(Marriage.id).where(Marriage.member_id == father_id, Marriage.spouse_id == mother_id)
        )
        if result.first() is not None:
            return
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="mother must be a recorded spouse of the father",
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
    for siblings in children_by_parent.values():  # a manual birth order wins; ties and unset keep creation order
        siblings.sort(key=lambda m: (m.birth_order is None, m.birth_order or 0, m.id))

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
    """Trưởng/Thứ/Út among same-gender siblings: manual birth_order first, then birth year (unknown last), then id.

    `siblings` must include `member` itself. None for a member with no parent or no male/female gender.
    """
    if member.parent_id is None or member.gender not in ("male", "female"):
        return None
    same_gender = sorted(
        (s for s in siblings if s.gender == member.gender),
        key=lambda s: (
            s.birth_order is None, s.birth_order or 0, s.birth_year is None, s.birth_year or 0, s.id
        ),
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


async def _branch_ref(db: AsyncSession, tree_id: int, member: Member) -> BranchRef | None:
    branch = await deepest_branch(db, member, await load_branches(db, tree_id))
    return BranchRef(id=branch.id, name=branch.name, color=branch.color) if branch else None


async def _member_in_tree(db: AsyncSession, tree_id: int, member_id: int) -> Member | None:
    member = await db.get(Member, member_id)
    return member if member is not None and member.tree_id == tree_id else None


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
async def get_tree(
    db: AsyncSession = Depends(get_db), ctx: TreeContext = Depends(get_read_context)
) -> MemberSkeletonNode | None:
    # ORDER BY id: without it Postgres returns an UPDATEd row after the others, so siblings would
    # reshuffle every time one of them is edited. Creation order is the stable, expected order.
    members_result = await db.execute(
        select(Member).where(Member.tree_id == ctx.tree.id).order_by(Member.id)
    )
    members = list(members_result.scalars().all())
    member_ids = [member.id for member in members]
    marriages_result = await db.execute(
        select(Marriage).where(Marriage.member_id.in_(member_ids)).order_by(Marriage.id)
    )
    marriages = list(marriages_result.scalars().all())
    full_tree = _build_tree(members, marriages)
    return _to_skeleton(full_tree) if full_tree is not None else None


@router.get("/{member_id}", response_model=MemberDetail)
async def get_member_detail(
    member_id: int,
    db: AsyncSession = Depends(get_db),
    ctx: TreeContext = Depends(get_read_context),
) -> MemberDetail:
    member = await _member_in_tree(db, ctx.tree.id, member_id)
    if member is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="member not found")

    marriages_result = await db.execute(
        select(Marriage)
        .where(Marriage.member_id == member_id)
        .order_by(Marriage.marriage_year.is_(None), Marriage.marriage_year, Marriage.id)
    )
    marriages = list(marriages_result.scalars().all())
    spouses = []
    for marriage in marriages:
        spouse = await db.get(Member, marriage.spouse_id)
        if spouse is not None:
            spouses.append(_spouse_info(marriage, spouse))

    sibling_rank = None
    if member.parent_id is not None:
        siblings_result = await db.execute(
            select(Member).where(Member.tree_id == ctx.tree.id, Member.parent_id == member.parent_id)
        )
        sibling_rank = _sibling_rank(member, list(siblings_result.scalars().all()))

    detail = MemberDetail(
        id=member.id,
        birth_year=member.birth_year,
        death_year=member.death_year,
        gender=member.gender,
        avatar_url=member.avatar_url,
        courtesy_name=member.courtesy_name,
        title=member.title,
        sibling_rank=sibling_rank,
        spouses=spouses,
        branch=await _branch_ref(db, ctx.tree.id, member),
        hometown=member.hometown,
        birth_month=member.birth_month,
        birth_day=member.birth_day,
        death_month=member.death_month,
        death_day=member.death_day,
        birth_is_lunar=member.birth_is_lunar,
        birth_leap_month=member.birth_leap_month,
        death_is_lunar=member.death_is_lunar,
        death_leap_month=member.death_leap_month,
        birth_order=member.birth_order,
        is_adopted=member.is_adopted,
        mother_id=member.mother_id,
    )
    if ctx.user is not None:  # guests (public tree) only get the fields above
        detail.phone = member.phone
        detail.email = member.email
        detail.notes = member.notes
        detail.residence = member.residence
        detail.burial_place = member.burial_place
        detail.burial_latitude = member.burial_latitude
        detail.burial_longitude = member.burial_longitude
    return detail


@router.post("", response_model=MemberRead, status_code=status.HTTP_201_CREATED)
async def create_member(
    payload: MemberCreate,
    db: AsyncSession = Depends(get_db),
    ctx: TreeContext = Depends(get_write_context),
) -> Member:
    if payload.parent_id is not None:
        parent = await _member_in_tree(db, ctx.tree.id, payload.parent_id)
        if parent is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="parent not found")

    await _check_mother(db, payload.parent_id, payload.mother_id)

    member = Member(tree_id=ctx.tree.id)
    _assign(member, payload)
    db.add(member)
    await db.commit()
    await db.refresh(member)
    return member


async def _apply_update(
    db: AsyncSession, ctx: TreeContext, member: Member, payload: MemberUpdate
) -> Member:
    if payload.parent_id is not None:
        if payload.parent_id == member.id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="a member cannot be its own parent",
            )
        new_parent = await _member_in_tree(db, ctx.tree.id, payload.parent_id)
        if new_parent is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="parent not found")
        if await _is_descendant(db, member.id, payload.parent_id):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="cannot set parent to one of the member's own descendants",
            )
    await _check_mother(db, payload.parent_id, payload.mother_id)

    _assign(member, payload)
    await db.commit()
    await db.refresh(member)
    return member


@router.put("/{member_id}", response_model=MemberRead)
async def update_member(
    member_id: int,
    payload: MemberUpdate,
    db: AsyncSession = Depends(get_db),
    ctx: TreeContext = Depends(get_write_context),
) -> Member:
    member = await _member_in_tree(db, ctx.tree.id, member_id)
    if member is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="member not found")
    return await _apply_update(db, ctx, member, payload)


@router.patch("/{member_id}", response_model=MemberRead)
async def patch_member(
    member_id: int,
    payload: MemberPatch,
    db: AsyncSession = Depends(get_db),
    ctx: TreeContext = Depends(get_write_context),
) -> Member:
    """Change only the fields sent (null clears one). The merged result is validated like a PUT, so a
    grid can save a single cell without re-sending the whole member."""
    member = await _member_in_tree(db, ctx.tree.id, member_id)
    if member is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="member not found")
    merged = member_values(member)
    merged.update(payload.model_dump(exclude_unset=True))
    try:
        merged_payload = MemberUpdate.model_validate(merged)
    except ValidationError as exc:
        raise RequestValidationError(exc.errors(include_url=False, include_context=False)) from None
    return await _apply_update(db, ctx, member, merged_payload)


@router.delete("/{member_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_member(
    member_id: int,
    db: AsyncSession = Depends(get_db),
    ctx: TreeContext = Depends(get_write_context),
) -> None:
    member = await _member_in_tree(db, ctx.tree.id, member_id)
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
    member_id: int,
    payload: MarriageCreate,
    db: AsyncSession = Depends(get_db),
    ctx: TreeContext = Depends(get_write_context),
) -> SpouseInfo:
    member = await _member_in_tree(db, ctx.tree.id, member_id)
    if member is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="member not found")

    spouse = Member(
        tree_id=ctx.tree.id,
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
    marriage_id: int,
    payload: MarriageUpdate,
    db: AsyncSession = Depends(get_db),
    ctx: TreeContext = Depends(get_write_context),
) -> SpouseInfo:
    marriage = await db.get(Marriage, marriage_id)
    if marriage is None or await _member_in_tree(db, ctx.tree.id, marriage.member_id) is None:
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
    member_id: int,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    ctx: TreeContext = Depends(get_write_context),
) -> dict[str, str]:
    member = await _member_in_tree(db, ctx.tree.id, member_id)
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
async def delete_avatar(
    member_id: int,
    db: AsyncSession = Depends(get_db),
    ctx: TreeContext = Depends(get_write_context),
) -> None:
    member = await _member_in_tree(db, ctx.tree.id, member_id)
    if member is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="member not found")

    settings = get_settings()
    _delete_avatar_file(settings.upload_dir, member.avatar_url)
    member.avatar_url = None
    await db.commit()
