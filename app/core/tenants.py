"""Creating trees and users (shared by the CLI and the tests). Routers do their own validation."""

import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.roles import ROLE_SUPERADMIN, ROLES, STATUS_ACTIVE, STATUSES
from app.core.security import hash_password
from app.models.tree import Tree
from app.models.user import User

SLUG_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
DEFAULT_TREE_NAME = "Gia phả"
DEFAULT_TREE_SLUG = "default"


class TenantError(ValueError):
    """A request that cannot be honoured (bad slug, duplicate, wrong role/tree combination...)."""


async def get_tree_by_slug(db: AsyncSession, slug: str) -> Tree | None:
    return (await db.execute(select(Tree).where(Tree.slug == slug))).scalar_one_or_none()


async def lowest_tree(db: AsyncSession) -> Tree | None:
    return (await db.execute(select(Tree).order_by(Tree.id).limit(1))).scalar_one_or_none()


async def create_tree(db: AsyncSession, name: str, slug: str) -> Tree:
    name = name.strip()
    if not name:
        raise TenantError("tree name must not be empty")
    if len(slug) > 60 or not SLUG_PATTERN.match(slug):
        raise TenantError("slug must be lowercase letters/digits separated by single hyphens (max 60)")
    if await get_tree_by_slug(db, slug) is not None:
        raise TenantError(f"a tree with slug {slug!r} already exists")
    tree = Tree(name=name, slug=slug)
    db.add(tree)
    await db.commit()
    await db.refresh(tree)
    return tree


async def rename_tree(
    db: AsyncSession, slug: str, *, name: str | None = None, new_slug: str | None = None
) -> Tree:
    tree = await get_tree_by_slug(db, slug)
    if tree is None:
        raise TenantError(f"no tree with slug {slug!r}")
    if name is not None:
        if not name.strip():
            raise TenantError("tree name must not be empty")
        tree.name = name.strip()
    if new_slug is not None and new_slug != tree.slug:
        if len(new_slug) > 60 or not SLUG_PATTERN.match(new_slug):
            raise TenantError("slug must be lowercase letters/digits separated by single hyphens (max 60)")
        if await get_tree_by_slug(db, new_slug) is not None:
            raise TenantError(f"a tree with slug {new_slug!r} already exists")
        tree.slug = new_slug
    await db.commit()
    await db.refresh(tree)
    return tree


async def get_or_create_default_tree(db: AsyncSession) -> Tree:
    return await lowest_tree(db) or await create_tree(db, DEFAULT_TREE_NAME, DEFAULT_TREE_SLUG)


def _check_role_and_tree(role: str, tree: Tree | None) -> None:
    if role not in ROLES:
        raise TenantError(f"role must be one of {', '.join(ROLES)}")
    if role == ROLE_SUPERADMIN and tree is not None:
        raise TenantError("a superadmin belongs to no tree")
    if role != ROLE_SUPERADMIN and tree is None:
        raise TenantError(f"a {role} must belong to a tree")


async def create_user(
    db: AsyncSession,
    *,
    email: str,
    full_name: str,
    password: str,
    role: str,
    tree: Tree | None,
    status: str = STATUS_ACTIVE,
) -> User:
    _check_role_and_tree(role, tree)
    if status not in STATUSES:
        raise TenantError(f"status must be one of {', '.join(STATUSES)}")
    if len(password) < 8:
        raise TenantError("password must be at least 8 characters")
    if (await db.execute(select(User).where(User.email == email))).scalar_one_or_none() is not None:
        raise TenantError(f"email {email!r} is already registered")
    user = User(
        email=email,
        hashed_password=hash_password(password),
        full_name=full_name,
        role=role,
        status=status,
        tree_id=tree.id if tree else None,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def set_user_role(db: AsyncSession, email: str, role: str, tree: Tree | None) -> User:
    _check_role_and_tree(role, tree)
    user = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
    if user is None:
        raise TenantError(f"no user with email {email!r}")
    user.role = role
    user.tree_id = tree.id if tree else None
    await db.commit()
    await db.refresh(user)
    return user
