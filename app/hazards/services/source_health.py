"""Salud de las fuentes de ingesta (ADR-0019, ADR-0021).

Servicio puro: recibe el estado de sync de cada fuente y su cadencia, y
decide frescura y salud. Lo comparten `/v1/sources/status` y los avisos (que
advierten cuando una fuente de la que dependen esta degradada); cada llamante
lee la BD por su cuenta.
"""

from collections.abc import Iterable, Mapping
from datetime import datetime

from app.core.attribution import ATTRIBUTIONS
from app.hazards.models import SourceSyncStateORM
from app.hazards.schemas.sources import SourcesStatusResponse, SourceStatus

_SYNC_JOB_SUFFIX = "_sync"


def sync_intervals(jobs: Iterable[tuple[str, int]]) -> dict[str, int]:
    """Cadencia por fuente desde (job_name, interval_seconds) de scheduled_jobs.

    Convencion: el job de una fuente se llama f"{source}_sync"; el resto de
    jobs (p. ej. notifications_deliver) no son fuentes.
    """
    return {
        name.removesuffix(_SYNC_JOB_SUFFIX): seconds
        for name, seconds in jobs
        if name.endswith(_SYNC_JOB_SUFFIX)
    }


def assess_sources(
    states: Iterable[SourceSyncStateORM],
    intervals: Mapping[str, int],
    *,
    now: datetime,
    staleness_factor: int,
    max_failures: int,
) -> SourcesStatusResponse:
    """Frescura y salud de cada fuente, juzgada contra su propia cadencia.

    Union de fuentes programadas y con estado: una fuente programada que
    nunca registro un run debe aparecer degradada, no desaparecer. Se juzga
    contra la cadencia de cada fuente, no contra un umbral fijo: EFFIS
    sincroniza cada 4 h y un umbral global daria falsos positivos.
    """
    by_source = {st.source: st for st in states}
    sources: list[SourceStatus] = []
    for source in sorted(set(intervals) | set(by_source)):
        st = by_source.get(source)
        interval = intervals.get(source)
        last_success = st.last_success_at if st else None
        seconds_since = (now - last_success).total_seconds() if last_success else None
        failures = st.consecutive_failures if st else 0

        stale = interval is not None and (
            seconds_since is None or seconds_since > staleness_factor * interval
        )
        healthy = not stale and failures < max_failures

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
                attribution=ATTRIBUTIONS.get(source),
            )
        )

    status = "ok" if all(s.healthy for s in sources) else "degraded"
    return SourcesStatusResponse(status=status, sources=sources)


__all__ = ["assess_sources", "sync_intervals"]
