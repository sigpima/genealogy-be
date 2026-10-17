"""Which tree is a request acting on? (see docs/superpowers/specs/2026-10-17-multi-tree-design.md)

- A signed-in user acts on their own tree. Nothing the client sends (cookie, header) can move a
  non-superadmin to another tree.
- A superadmin has no tree: `X-Tree-Id` picks one, default is the lowest-id tree.
- Guests and signup use the `tree_slug` cookie (set by visiting /t/<slug>); with exactly one tree
  that tree is used without a cookie.
"""

from dataclasses import dataclass

from fastapi import HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.roles import ROLE_SUPERADMIN
from app.core.tenants import get_tree_by_slug, lowest_tree
from app.models.tree import Tree
from app.models.user import User

TREE_SLUG_COOKIE = "tree_slug"
TREE_ID_HEADER = "X-Tree-Id"


@dataclass
class TreeContext:
    """The tree a request acts on, and who is acting (None = a guest on a public tree)."""

    tree: Tree
    user: User | None


def _not_found(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail)


async def tree_for_user(user: User, request: Request, db: AsyncSession) -> Tree:
    if user.role == ROLE_SUPERADMIN:
        raw = request.headers.get(TREE_ID_HEADER)
        if raw is None:
            tree = await lowest_tree(db)
            if tree is None:
                raise _not_found("there is no tree yet")
            return tree
        try:
            tree = await db.get(Tree, int(raw))
        except ValueError:
            tree = None
        if tree is None:
            raise _not_found("tree not found")
        return tree
    if user.tree_id is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="account has no tree")
    tree = await db.get(Tree, user.tree_id)
    if tree is None:
        raise _not_found("tree not found")
    return tree


async def public_tree(request: Request, db: AsyncSession, *, ambiguous_status: int = 404) -> Tree:
    """The tree a guest/signup refers to: the cookie's tree, else the only tree there is."""
    slug = request.cookies.get(TREE_SLUG_COOKIE)
    if slug:
        tree = await get_tree_by_slug(db, slug)
        if tree is None:
            raise _not_found("tree not found")
        return tree
    count = (await db.execute(select(func.count()).select_from(Tree))).scalar_one()
    if count == 1:
        return (await db.execute(select(Tree))).scalar_one()
    detail = "tree required: open your family's link" if count > 1 else "there is no tree yet"
    raise HTTPException(status_code=ambiguous_status, detail=detail)
