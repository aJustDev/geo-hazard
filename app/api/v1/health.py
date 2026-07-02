from fastapi import APIRouter, Request
from sqlalchemy import text
from starlette.responses import JSONResponse

from app.core.db import engine

router = APIRouter(tags=["Health"])


@router.get("/health/liveness")
async def liveness():
    return {"status": "alive"}


@router.get("/health/readiness")
async def readiness(request: Request):
    if not getattr(request.app.state, "ready", False):
        return JSONResponse(status_code=503, content={"status": "not ready"})
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception:
        return JSONResponse(status_code=503, content={"status": "database unavailable"})
    return {"status": "ready"}
