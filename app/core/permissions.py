"""Access rules shared by the routers.

- `get_current_user` (routers/auth.py): any *active* signed-in user (401 without a valid token,
  403 when the account is pending/disabled).
- `get_read_context`: who may *read* and which tree: an active user (their tree), or a guest when
  the tree is public.
- `get_write_context`: an admin/superadmin and the tree they act on.
- `get_user_context`: any signed-in active user (not a guest) and their tree.
- `require_superadmin`: the platform owner only (managing trees).
- `can_read_tree`: may this request read a given tree? (for files, which carry no tree context)
"""

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.roles import ADMIN_ROLES, ROLE_SUPERADMIN, get_tree_settings
from app.core.tenancy import TreeContext, public_tree, tree_for_user
from app.db.session import get_db
from app.models.user import User
from app.routers.auth import ACCESS_TOKEN_COOKIE, get_current_user, get_token_from_request


async def require_admin(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role not in ADMIN_ROLES:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="admin only")
    return current_user


async def require_superadmin(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role != ROLE_SUPERADMIN:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="superadmin only")
    return current_user


async def get_user_context(
    request: Request, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
) -> TreeContext:
    """Any signed-in, active user and the tree they act on (no guests): the door for proposing changes."""
    return TreeContext(tree=await tree_for_user(user, request, db), user=user)


async def get_write_context(
    request: Request, db: AsyncSession = Depends(get_db), admin: User = Depends(require_admin)
) -> TreeContext:
    return TreeContext(tree=await tree_for_user(admin, request, db), user=admin)


async def get_read_context(request: Request, db: AsyncSession = Depends(get_db)) -> TreeContext:
    has_credentials = bool(
        request.cookies.get(ACCESS_TOKEN_COOKIE) or request.headers.get("Authorization")
    )
    if has_credentials:
        try:
            user = await get_current_user(get_token_from_request(request), db)
            return TreeContext(tree=await tree_for_user(user, request, db), user=user)
        except HTTPException as exc:
            # A bad/expired token degrades to "guest" (it may still read a public tree); a real
            # pending/disabled account (403) or a tree error stays as it is.
            if exc.status_code != status.HTTP_401_UNAUTHORIZED:
                raise
    # Guest: only a public tree may be read. Anything unresolvable is a plain 401 so the frontend
    # sends the visitor to the login page.
    unauthenticated = HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="not authenticated")
    try:
        tree = await public_tree(request, db)
    except HTTPException:
        raise unauthenticated
    if (await get_tree_settings(db, tree.id))["visibility"] != "public":
        raise unauthenticated
    return TreeContext(tree=tree, user=None)


async def read_access(request: Request, db: AsyncSession, tree_id: int, *, allow_guests: bool = True) -> tuple[bool, User | None]:
    """(may read, the signed-in user if that is what grants it). Same rules as `get_read_context`, for a tree that is
    already known (no cookie/header lookup): an active member of that tree or the superadmin, or anybody when that tree
    is public. A bad token or a pending/disabled account counts as a stranger. `allow_guests=False` is for material
    that guests of a public tree never see (media, places): only the first branch can say yes."""
    if request.cookies.get(ACCESS_TOKEN_COOKIE) or request.headers.get("Authorization"):
        try:
            user = await get_current_user(get_token_from_request(request), db)
        except HTTPException:
            user = None
        if user is not None and (user.role == ROLE_SUPERADMIN or user.tree_id == tree_id):
            return True, user
    if allow_guests and (await get_tree_settings(db, tree_id))["visibility"] == "public":
        return True, None
    return False, None


async def can_read_tree(request: Request, db: AsyncSession, tree_id: int, *, allow_guests: bool = True) -> bool:
    return (await read_access(request, db, tree_id, allow_guests=allow_guests))[0]
