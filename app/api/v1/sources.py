from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import get_session
from app.core.jobs.models import ScheduledJobORM
from app.hazards.repos.sync_state import SourceSyncStateRepo
from app.hazards.schemas.sources import SourcesStatusResponse
from app.hazards.services.source_health import assess_sources, sync_intervals

# Vive en app.api porque cruza dos contextos: el estado de ingesta
# (hazards.source_sync_state) y la cadencia de scheduling (core.jobs). Ambos
# imports son legales; los contratos solo prohiben core -> api/hazards. La
# regla de salud es un servicio puro compartido con los avisos (ADR-0021).
router = APIRouter(prefix="/sources", tags=["Sources"])


# Frescura por fuente: superficie de confianza para integradores y base de la
# alerta operativa (ADR-0019). Se juzga contra la cadencia propia de cada fuente
# (scheduled_jobs), no contra un umbral fijo: EFFIS sincroniza cada 4h y un
# umbral global daria falsos positivos.
@router.get(
    "/status",
    response_model=SourcesStatusResponse,
    summary="Freshness of each source",
    description=(
        "Per-source sync freshness, judged against each source's own cadence, with "
        "consecutive failures, the attribution each source requires and a top-level "
        "`ok`/`degraded`. `last_success_at` is the time of the source's last update."
    ),
)
async def sources_status(session: Annotated[AsyncSession, Depends(get_session)]):
    states = await SourceSyncStateRepo(session).list_all()
    jobs = (
        await session.execute(select(ScheduledJobORM.job_name, ScheduledJobORM.interval_seconds))
    ).all()
    return assess_sources(
        states,
        sync_intervals((name, secs) for name, secs in jobs),
        now=datetime.now(UTC),
        staleness_factor=settings.SOURCE_STALENESS_FACTOR,
        max_failures=settings.SOURCE_MAX_FAILURES,
    )
