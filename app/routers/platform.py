"""Platform level (superadmin only): overview, platform log, system health. Independent of the tree the superadmin currently acts on."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import require_superadmin
from app.core.platform_overview import compute_platform_overview
from app.db.session import get_db
from app.schemas.platform import PlatformOverview

router = APIRouter(prefix="/platform", tags=["platform"], dependencies=[Depends(require_superadmin)])


@router.get("/overview", response_model=PlatformOverview)
async def overview(db: AsyncSession = Depends(get_db)) -> PlatformOverview:
    return await compute_platform_overview(db)
