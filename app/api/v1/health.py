from fastapi import APIRouter, Request
from pydantic import Field
from sqlalchemy import text
from starlette.responses import JSONResponse

from app.core.db import engine
from app.core.schema import BaseSchema

router = APIRouter(tags=["Health"])


class HealthStatus(BaseSchema):
    status: str = Field(examples=["ready"])


@router.get(
    "/health/liveness",
    response_model=HealthStatus,
    summary="Liveness probe",
    description="The process is up. Does not touch the database.",
)
async def liveness():
    return {"status": "alive"}


@router.get(
    "/health/readiness",
    response_model=HealthStatus,
    summary="Readiness probe",
    description="The app started against a reachable database and can still reach it.",
    responses={503: {"model": HealthStatus, "description": "Not ready or database unavailable."}},
)
async def readiness(request: Request):
    if not getattr(request.app.state, "ready", False):
        return JSONResponse(status_code=503, content={"status": "not ready"})
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception:
        return JSONResponse(status_code=503, content={"status": "database unavailable"})
    return {"status": "ready"}
