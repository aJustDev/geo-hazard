from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.jobs.models import ScheduledJobORM
from app.hazards.models import SourceSyncStateORM
from app.hazards.services.source_health import assess_sources, sync_intervals


async def degraded_sources(session: AsyncSession, *, now: datetime) -> list[str]:
    """Fuentes no sanas segun la misma regla que /v1/sources/status."""
    states = (await session.execute(select(SourceSyncStateORM))).scalars().all()
    jobs = await session.execute(select(ScheduledJobORM.job_name, ScheduledJobORM.interval_seconds))
    report = assess_sources(
        states,
        sync_intervals((name, seconds) for name, seconds in jobs),
        now=now,
        staleness_factor=settings.SOURCE_STALENESS_FACTOR,
        max_failures=settings.SOURCE_MAX_FAILURES,
    )
    return [s.source for s in report.sources if not s.healthy]


__all__ = ["degraded_sources"]
