from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.config import get_settings
from app.routers.admin import router as admin_router
from app.routers.articles import router as articles_router
from app.routers.audit import router as audit_router
from app.routers.auth import router as auth_router
from app.routers.book import router as book_router
from app.routers.branches import router as branches_router
from app.routers.calendar import router as calendar_router
from app.routers.events import router as events_router
from app.routers.export import router as export_router
from app.routers.generation_words import router as generation_words_router
from app.routers.invitations import admin_router as invitations_admin_router
from app.routers.invitations import public_router as invitations_public_router
from app.routers.member import router as member_router
from app.routers.invite_public import router as invite_public_router
from app.routers.member_invites import router as member_invites_router
from app.routers.media import router as media_router
from app.routers.member_search import router as member_search_router
from app.routers.member_tools import router as member_tools_router
from app.routers.notifications import router as notifications_router
from app.routers.places import router as places_router
from app.routers.platform import router as platform_router
from app.routers.requests import router as requests_router
from app.routers.timeline import router as timeline_router
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


@app.middleware("http")
async def security_headers(request: Request, call_next):
    """Cheap, safe-everywhere headers. HSTS and CSP are deliberately not here: HSTS belongs to whatever terminates
    HTTPS (sending it over plain HTTP is wrong) and the CSP to the web app that serves the pages."""
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("X-Frame-Options", "DENY")
    return response


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
app.include_router(articles_router)
app.include_router(book_router)
app.include_router(export_router)
app.include_router(timeline_router)
app.include_router(generation_words_router)
app.include_router(invitations_admin_router)
app.include_router(invitations_public_router)
app.include_router(member_invites_router)
app.include_router(invite_public_router)
app.include_router(trees_router)
app.include_router(platform_router)
app.include_router(uploads_router)


@app.get("/health")
async def health() -> dict[str, str]:
    """Liveness probe for container healthchecks (public, no DB access on purpose)."""
    return {"status": "ok"}


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(status_code=500, content={"detail": "internal server error"})
