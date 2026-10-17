from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.roles import get_tree_settings
from app.core.tenancy import public_tree
from app.db.session import get_db
from app.schemas.admin import SiteInfo

router = APIRouter(prefix="/site", tags=["site"])


@router.get("/info", response_model=SiteInfo)
async def site_info(request: Request, db: AsyncSession = Depends(get_db)) -> SiteInfo:
    """Public, unauthenticated: lets the login/signup pages explain what will happen.

    Describes the tree the visitor refers to (the `tree_slug` cookie, or the only tree); 404 when that
    cannot be decided.
    """
    tree = await public_tree(request, db)
    settings = await get_tree_settings(db, tree.id)
    return SiteInfo(**settings, tree_name=tree.name, tree_slug=tree.slug)
