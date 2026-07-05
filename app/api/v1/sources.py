from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import get_session
from app.core.jobs.models import ScheduledJobORM
from app.hazards.repos.sync_state import SourceSyncStateRepo
from app.hazards.schemas.sources import SourcesStatusResponse, SourceStatus

# Vive en app.api porque cruza dos contextos: el estado de ingesta
# (hazards.source_sync_state) y la cadencia de scheduling (core.jobs). Ambos
# imports son legales; los contratos solo prohiben core -> api/hazards.
router = APIRouter(prefix="/sources", tags=["Sources"])


@router.get("/status", response_model=SourcesStatusResponse)
async def sources_status(session: Annotated[AsyncSession, Depends(get_session)]):
    """Frescura por fuente: superficie de confianza para integradores y base de
    la alerta operativa (ADR-0019). La frescura se juzga contra la cadencia
    propia de cada fuente (scheduled_jobs), no contra un umbral fijo: EFFIS
    sincroniza cada 4h y un umbral global daria falsos positivos.
    """
    repo = SourceSyncStateRepo(session)
    states = {st.source: st for st in await repo.list_all()}

    # Intervalo de cadencia por fuente. Convencion: job_name = f"{source}_sync".
    rows = (
        await session.execute(select(ScheduledJobORM.job_name, ScheduledJobORM.interval_seconds))
    ).all()
    intervals = {name.removesuffix("_sync"): secs for name, secs in rows if name.endswith("_sync")}

    # Union: una fuente programada sin fila de estado (nunca registro un run)
    # debe aparecer como degraded, no desaparecer del informe.
    now = datetime.now(UTC)
    sources: list[SourceStatus] = []
    for source in sorted(set(intervals) | set(states)):
        st = states.get(source)
        interval = intervals.get(source)
        last_success = st.last_success_at if st else None
        seconds_since = (now - last_success).total_seconds() if last_success else None
        failures = st.consecutive_failures if st else 0

        stale = interval is not None and (
            seconds_since is None or seconds_since > settings.SOURCE_STALENESS_FACTOR * interval
        )
        healthy = not stale and failures < settings.SOURCE_MAX_FAILURES

        sources.append(
            SourceStatus(
                source=source,
                last_run_at=st.last_run_at if st else None,
                last_success_at=last_success,
                seconds_since_success=seconds_since,
                consecutive_failures=failures,
                has_error=bool(st and st.last_error),
                interval_seconds=interval,
                stale=stale,
                healthy=healthy,
            )
        )

    status = "ok" if all(s.healthy for s in sources) else "degraded"
    return SourcesStatusResponse(status=status, sources=sources)
