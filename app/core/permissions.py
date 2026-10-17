"""Access rules shared by the routers.

- `get_current_user` (routers/auth.py): any *active* signed-in user (401 without a valid token,
  403 when the account is pending/disabled).
- `require_admin`: an active admin.
- `get_viewer`: who may *read*: an active user, or `None` (a guest) when the site is public.
"""

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.roles import ROLE_ADMIN, get_site_settings
from app.db.session import get_db
from app.models.user import User
from app.routers.auth import ACCESS_TOKEN_COOKIE, get_current_user, get_token_from_request


async def require_admin(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role != ROLE_ADMIN:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="admin only")
    return current_user


async def get_viewer(request: Request, db: AsyncSession = Depends(get_db)) -> User | None:
    site_is_public = (await get_site_settings(db))["visibility"] == "public"
    has_credentials = bool(
        request.cookies.get(ACCESS_TOKEN_COOKIE) or request.headers.get("Authorization")
    )
    if has_credentials:
        try:
            return await get_current_user(get_token_from_request(request), db)
        except HTTPException as exc:
            # A bad/expired token must not lock a guest out of a public site, but a real account
            # that is pending/disabled (403) stays refused.
            if exc.status_code == status.HTTP_401_UNAUTHORIZED and site_is_public:
                return None
            raise
    if site_is_public:
        return None
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="not authenticated")
