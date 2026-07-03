from fastapi import APIRouter

from app.analytics.api import analytics_router
from app.api.v1.health import router as health_router
from app.hazards.api import events_router

v1_router = APIRouter(prefix="/v1")
v1_router.include_router(health_router)
v1_router.include_router(events_router)
v1_router.include_router(analytics_router)

__all__ = ["v1_router"]
