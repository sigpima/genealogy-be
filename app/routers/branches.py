"""Branches (chi/phái). Reads follow the tree's visibility; writes are admin-only. Everything is per tree and a
head or branch of another tree answers 404."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.core.permissions import get_read_context, get_write_context
from app.core.tenancy import TreeContext
from app.core.tree_layout import load_layout
from app.db.session import get_db
from app.models.branch import Branch
from app.models.member import Member
from app.schemas.branch import BranchCreate, BranchRead, BranchUpdate

router = APIRouter(prefix="/branches", tags=["branches"])

PALETTE = ("#8b1a1a", "#2e7d32", "#1565c0", "#ef6c00", "#6a1b9a", "#00838f", "#ad1457", "#4e342e")


def _next_color(existing: list[Branch]) -> str:
    used = {b.color for b in existing}
    unused = [c for c in PALETTE if c not in used]
    return unused[0] if unused else PALETTE[len(existing) % len(PALETTE)]


async def _describe(db: AsyncSession, ctx: TreeContext) -> list[BranchRead]:
    branches = list((await db.execute(select(Branch).where(Branch.tree_id == ctx.tree.id))).scalars().all())
    layout = await load_layout(db, ctx.tree.id, branches)
    rows = [
        BranchRead(
            id=b.id,
            name=b.name,
            color=b.color,
            description=b.description,
            root_member_id=b.root_member_id,
            root_name=layout.by_id[b.root_member_id].full_name,
            root_generation=layout.generation.get(b.root_member_id, 0),
            member_count=len(layout.subtree_ids(b.root_member_id)),
        )
        for b in branches
        if b.root_member_id in layout.by_id
    ]
    return sorted(rows, key=lambda r: (r.root_generation, r.id))


async def _head_in_tree(db: AsyncSession, ctx: TreeContext, member_id: int) -> Member:
    member = await db.get(Member, member_id)
    if member is None or member.tree_id != ctx.tree.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="member not found")
    return member


async def _branch_in_tree(db: AsyncSession, ctx: TreeContext, branch_id: int) -> Branch:
    branch = await db.get(Branch, branch_id)
    if branch is None or branch.tree_id != ctx.tree.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="branch not found")
    return branch


async def _one(db: AsyncSession, ctx: TreeContext, branch_id: int) -> BranchRead:
    return next(r for r in await _describe(db, ctx) if r.id == branch_id)


async def _ensure_head_is_free(db: AsyncSession, member_id: int, *, except_branch: int | None = None) -> None:
    taken = (await db.execute(select(Branch.id).where(Branch.root_member_id == member_id))).scalar_one_or_none()
    if taken is not None and taken != except_branch:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="this person already heads a branch")


@router.get("", response_model=list[BranchRead])
async def list_branches(db: AsyncSession = Depends(get_db), ctx: TreeContext = Depends(get_read_context)):
    return await _describe(db, ctx)


@router.post("", response_model=BranchRead, status_code=status.HTTP_201_CREATED)
async def create_branch(
    payload: BranchCreate, db: AsyncSession = Depends(get_db), ctx: TreeContext = Depends(get_write_context)
) -> BranchRead:
    await _head_in_tree(db, ctx, payload.root_member_id)
    await _ensure_head_is_free(db, payload.root_member_id)
    existing = list((await db.execute(select(Branch).where(Branch.tree_id == ctx.tree.id))).scalars().all())
    branch = Branch(
        tree_id=ctx.tree.id,
        name=payload.name,
        color=payload.color or _next_color(existing),
        description=payload.description,
        root_member_id=payload.root_member_id,
    )
    db.add(branch)
    head = await db.get(Member, payload.root_member_id)
    audit.record(
        db,
        tree_id=ctx.tree.id,
        actor=ctx.user,
        action="branch.create",
        member_id=head.id,
        member_name=head.full_name,
        changes={"name": [None, branch.name], "color": [None, branch.color], "description": [None, branch.description]},
        details={"branch_name": branch.name},
    )
    try:
        await db.commit()
    except IntegrityError:  # two admins racing for the same head
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="this person already heads a branch") from None
    await db.refresh(branch)
    return await _one(db, ctx, branch.id)


@router.put("/{branch_id}", response_model=BranchRead)
async def update_branch(
    branch_id: int,
    payload: BranchUpdate,
    db: AsyncSession = Depends(get_db),
    ctx: TreeContext = Depends(get_write_context),
) -> BranchRead:
    branch = await _branch_in_tree(db, ctx, branch_id)
    await _head_in_tree(db, ctx, payload.root_member_id)
    await _ensure_head_is_free(db, payload.root_member_id, except_branch=branch.id)
    before = {"name": branch.name, "color": branch.color, "description": branch.description, "root_member_id": branch.root_member_id}
    branch.name = payload.name
    branch.root_member_id = payload.root_member_id
    branch.description = payload.description
    if payload.color is not None:
        branch.color = payload.color
    after = {"name": branch.name, "color": branch.color, "description": branch.description, "root_member_id": branch.root_member_id}
    changes = audit.diff_values(before, after)
    if changes:
        head = await db.get(Member, branch.root_member_id)
        audit.record(
            db,
            tree_id=ctx.tree.id,
            actor=ctx.user,
            action="branch.update",
            member_id=head.id,
            member_name=head.full_name,
            changes=changes,
            details={"branch_name": branch.name},
        )
    await db.commit()
    return await _one(db, ctx, branch.id)


@router.delete("/{branch_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_branch(
    branch_id: int, db: AsyncSession = Depends(get_db), ctx: TreeContext = Depends(get_write_context)
) -> None:
    branch = await _branch_in_tree(db, ctx, branch_id)
    head = await db.get(Member, branch.root_member_id)
    audit.record(
        db,
        tree_id=ctx.tree.id,
        actor=ctx.user,
        action="branch.delete",
        member_id=head.id,
        member_name=head.full_name,
        changes={"name": [branch.name, None], "color": [branch.color, None], "description": [branch.description, None]},
        details={"branch_name": branch.name},
    )
    await db.delete(branch)
    await db.commit()
