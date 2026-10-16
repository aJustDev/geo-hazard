from datetime import datetime
from typing import Literal

from pydantic import ConfigDict

from app.core.attribution import SourceAttribution
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
    # Atribucion exigida por la fuente; None si aun no tiene entrada.
    attribution: SourceAttribution | None


class SourcesStatusResponse(BaseSchema):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "status": "ok",
                    "sources": [
                        {
                            "source": "aemet",
                            "last_run_at": "2026-10-16T08:17:05Z",
                            "last_success_at": "2026-10-16T08:17:05Z",
                            "seconds_since_success": 1453.6,
                            "consecutive_failures": 0,
                            "has_error": False,
                            "interval_seconds": 1800,
                            "stale": False,
                            "healthy": True,
                            "attribution": {
                                "source": "aemet",
                                "text": "Fuente: AEMET",
                                "url": "https://www.aemet.es/es/nota_legal",
                            },
                        }
                    ],
                }
            ]
        }
    )

    status: Literal["ok", "degraded"]
    sources: list[SourceStatus]
