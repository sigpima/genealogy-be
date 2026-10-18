"""Platform level: the superadmin's view of all families (superadmin only).

Creating a tree also creates its first admin, who can then invite/approve the rest from /admin. Adding more
admins, approving users and changing a family's settings happens in /admin while acting on that tree."""

import secrets

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit, platform_log
from app.core.permissions import require_superadmin
from app.core.roles import ROLE_ADMIN, STATUS_ACTIVE
from app.core.tenancy import tree_for_user
from app.core.tenants import TenantError, create_tree, create_user, get_tree_by_slug
from app.db.session import get_db
from app.models.audit_log import AuditLog
from app.models.member import Member
from app.models.tree import Tree
from app.models.user import User
from app.core.tree_removal import delete_tree_data
from app.schemas.tree import TreeAdmin, TreeCreate, TreeCreated, TreeDelete, TreeRead, TreeUpdate

router = APIRouter(prefix="/trees", tags=["trees"], dependencies=[Depends(require_superadmin)])


async def _describe(db: AsyncSession, trees: list[Tree], current_id: int | None) -> list[TreeRead]:
    ids = [t.id for t in trees]
    members = dict(
        (await db.execute(select(Member.tree_id, func.count()).where(Member.tree_id.in_(ids)).group_by(Member.tree_id))).all()
    )
    users = (await db.execute(select(User).where(User.tree_id.in_(ids)).order_by(User.id))).scalars().all()
    audited = dict((await db.execute(select(AuditLog.tree_id, func.max(AuditLog.created_at)).where(AuditLog.tree_id.in_(ids)).group_by(AuditLog.tree_id))).all())
    reads = []
    for tree in trees:
        own = [u for u in users if u.tree_id == tree.id]
        reads.append(
            TreeRead(
                id=tree.id,
                name=tree.name,
                slug=tree.slug,
                created_at=tree.created_at,
                member_count=members.get(tree.id, 0),
                user_count=len(own),
                admins=[
                    TreeAdmin(id=u.id, email=u.email, full_name=u.full_name, status=u.status)
                    for u in own
                    if u.role == ROLE_ADMIN
                ],
                is_current=tree.id == current_id,
                status=tree.status,
                last_activity=max([t for t in [audited.get(tree.id), *(u.last_login_at for u in own)] if t is not None], default=None),
            )
        )
    return reads


@router.get("", response_model=list[TreeRead])
async def list_trees(
    request: Request, admin: User = Depends(require_superadmin), db: AsyncSession = Depends(get_db)
) -> list[TreeRead]:
    trees = list((await db.execute(select(Tree).order_by(Tree.id))).scalars().all())
    try:
        current_id = (await tree_for_user(admin, request, db)).id
    except HTTPException:  # an explicit but wrong X-Tree-Id: still list everything, nothing is current
        current_id = None
    return await _describe(db, trees, current_id)


@router.post("", response_model=TreeCreated, status_code=status.HTTP_201_CREATED)
async def create_family(
    payload: TreeCreate, actor: User = Depends(require_superadmin), db: AsyncSession = Depends(get_db)
) -> TreeCreated:
    # Everything that can be refused is checked BEFORE the first write: create_tree/create_user each commit,
    # so a late failure would leave a tree without its admin.
    if await get_tree_by_slug(db, payload.slug) is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="slug already in use")
    if (await db.execute(select(User).where(User.email == payload.admin_email))).scalar_one_or_none() is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="email already registered")
    password = payload.admin_password or secrets.token_urlsafe(12)
    try:
        tree = await create_tree(db, payload.name, payload.slug)
        admin = await create_user(
            db,
            email=payload.admin_email,
            full_name=payload.admin_name,
            password=password,
            role=ROLE_ADMIN,
            tree=tree,
            status=STATUS_ACTIVE,
        )
    except TenantError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from None
    platform_log.record(db, actor=actor, action="tree.create", tree=tree, details={"slug": tree.slug, "admin_email": admin.email})
    await db.commit()  # create_tree/create_user committed already; the log line follows in its own commit
    [read] = await _describe(db, [tree], None)
    return TreeCreated(
        tree=read,
        admin=TreeAdmin(id=admin.id, email=admin.email, full_name=admin.full_name, status=admin.status),
        admin_password=None if payload.admin_password else password,
    )


@router.patch("/{tree_id}", response_model=TreeRead)
async def update_family(
    tree_id: int,
    payload: TreeUpdate,
    request: Request,
    admin: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
) -> TreeRead:
    tree = await db.get(Tree, tree_id)
    if tree is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="tree not found")
    before = {"name": tree.name, "slug": tree.slug}
    if payload.slug is not None and payload.slug != tree.slug:
        if await get_tree_by_slug(db, payload.slug) is not None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="slug already in use")
        tree.slug = payload.slug
    if payload.name is not None:
        tree.name = payload.name
    changes = audit.diff_values(before, {"name": tree.name, "slug": tree.slug})
    if changes:
        platform_log.record(db, actor=admin, action="tree.update", tree=tree, details={"changes": changes})
    await db.commit()
    await db.refresh(tree)
    try:
        current_id = (await tree_for_user(admin, request, db)).id
    except HTTPException:
        current_id = None
    [read] = await _describe(db, [tree], current_id)
    return read


async def _set_status(tree_id: int, wanted: str, actor: User, request: Request, db: AsyncSession) -> TreeRead:
    tree = await db.get(Tree, tree_id)
    if tree is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="tree not found")
    if tree.status == wanted:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"tree is already {wanted}")
    tree.status = wanted
    platform_log.record(db, actor=actor, action="tree.pause" if wanted == "paused" else "tree.resume", tree=tree)
    await db.commit()
    await db.refresh(tree)
    try:
        current_id = (await tree_for_user(actor, request, db)).id
    except HTTPException:
        current_id = None
    [read] = await _describe(db, [tree], current_id)
    return read


@router.post("/{tree_id}/pause", response_model=TreeRead)
async def pause_family(
    tree_id: int, request: Request, actor: User = Depends(require_superadmin), db: AsyncSession = Depends(get_db)
) -> TreeRead:
    """Stop a family for everybody in it (nothing is lost); see app/core/tenancy.py::is_paused for every door that closes."""
    return await _set_status(tree_id, "paused", actor, request, db)


@router.post("/{tree_id}/resume", response_model=TreeRead)
async def resume_family(
    tree_id: int, request: Request, actor: User = Depends(require_superadmin), db: AsyncSession = Depends(get_db)
) -> TreeRead:
    return await _set_status(tree_id, "active", actor, request, db)


@router.delete("/{tree_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_family(
    tree_id: int, payload: TreeDelete, actor: User = Depends(require_superadmin), db: AsyncSession = Depends(get_db)
) -> None:
    """Delete a PAUSED family for good: every row of it and its files. The slug in the body must match."""
    tree = await db.get(Tree, tree_id)
    if tree is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="tree not found")
    if tree.status != "paused":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="pause the family before deleting it")
    if payload.slug != tree.slug:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="the slug does not match")
    name, slug = tree.name, tree.slug
    removal = await delete_tree_data(db, tree)
    platform_log.record(db, actor=actor, action="tree.delete", tree_id=tree_id, tree_name=name, details={"slug": slug, **removal.counts})
    await db.commit()
    removal.unlink()  # only after the commit succeeded
