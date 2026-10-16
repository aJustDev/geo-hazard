from fastapi import APIRouter

from app.analytics.api import analytics_router
from app.api.v1.health import router as health_router
from app.api.v1.sources import router as sources_router
from app.core.schema import error_responses
from app.hazards.api import events_router

# El limite global de peticiones (ADR-0017) aplica a toda /v1.
v1_router = APIRouter(prefix="/v1", responses=error_responses(429))
v1_router.include_router(health_router)
v1_router.include_router(events_router)
v1_router.include_router(analytics_router)
v1_router.include_router(sources_router)

__all__ = ["v1_router"]
