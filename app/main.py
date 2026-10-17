from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.config import get_settings
from app.routers.admin import router as admin_router
from app.routers.audit import router as audit_router
from app.routers.auth import router as auth_router
from app.routers.branches import router as branches_router
from app.routers.calendar import router as calendar_router
from app.routers.events import router as events_router
from app.routers.member import router as member_router
from app.routers.media import router as media_router
from app.routers.member_search import router as member_search_router
from app.routers.member_tools import router as member_tools_router
from app.routers.notifications import router as notifications_router
from app.routers.places import router as places_router
from app.routers.requests import router as requests_router
from app.routers.site import router as site_router
from app.routers.trees import router as trees_router
from app.routers.uploads import router as uploads_router

settings = get_settings()

Path(settings.upload_dir, "avatars").mkdir(parents=True, exist_ok=True)

app = FastAPI(title="genealogy-api")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Avatars are NOT a static mount: app/routers/uploads.py checks who may see each file.
app.include_router(auth_router)
app.include_router(member_search_router)  # before member_router: /members/search must beat /members/{id}
app.include_router(member_tools_router)  # before member_router: /members/table must beat /members/{id}
app.include_router(member_router)
app.include_router(admin_router)
app.include_router(site_router)
app.include_router(branches_router)
app.include_router(audit_router)
app.include_router(requests_router)
app.include_router(calendar_router)
app.include_router(events_router)
app.include_router(notifications_router)
app.include_router(places_router)
app.include_router(media_router)
app.include_router(trees_router)
app.include_router(uploads_router)


@app.get("/health")
async def health() -> dict[str, str]:
    """Liveness probe for container healthchecks (public, no DB access on purpose)."""
    return {"status": "ok"}


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(status_code=500, content={"detail": "internal server error"})
