from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.roles import get_site_settings
from app.db.session import get_db
from app.schemas.admin import SiteSettingsPayload

router = APIRouter(prefix="/site", tags=["site"])


@router.get("/info", response_model=SiteSettingsPayload)
async def site_info(db: AsyncSession = Depends(get_db)) -> dict[str, str]:
    """Public, unauthenticated: lets the login/signup pages explain what will happen."""
    return await get_site_settings(db)
