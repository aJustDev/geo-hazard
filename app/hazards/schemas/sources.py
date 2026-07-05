from datetime import datetime
from typing import Literal

from app.core.schema import BaseSchema


class SourceStatus(BaseSchema):
    source: str
    last_run_at: datetime | None
    last_success_at: datetime | None
    # Segundos desde el ultimo exito; None si nunca tuvo uno.
    seconds_since_success: float | None
    consecutive_failures: int
    has_error: bool
    # Cadencia esperada (scheduled_jobs); None si la fuente no esta programada.
    interval_seconds: int | None
    # stale: lleva sin exito mas de STALENESS_FACTOR * su intervalo (o nunca).
    stale: bool
    # healthy: ni stale ni con demasiados fallos consecutivos.
    healthy: bool


class SourcesStatusResponse(BaseSchema):
    status: Literal["ok", "degraded"]
    sources: list[SourceStatus]
