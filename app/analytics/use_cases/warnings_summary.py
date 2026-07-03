from dataclasses import dataclass

from app.analytics.paths import source_snapshot
from app.analytics.queries.warnings import summary_by_phenomenon
from app.analytics.schemas.warnings import WarningsSummaryResponse, WarningsSummaryRow
from app.core.concurrency import run_blocking


@dataclass(slots=True)
class WarningsSummaryUseCase:
    """Avisos por fenomeno y nivel desde el snapshot GeoParquet de AEMET."""

    async def execute(self, *, year: int, phenomenon_code: str | None) -> WarningsSummaryResponse:
        snapshot = source_snapshot("aemet")
        if not snapshot.exists():
            return WarningsSummaryResponse(year=year, rows=[])
        rows = await run_blocking(
            summary_by_phenomenon,
            snapshot=str(snapshot),
            year=year,
            phenomenon_code=phenomenon_code,
        )
        return WarningsSummaryResponse(year=year, rows=[WarningsSummaryRow(**row) for row in rows])


__all__ = ["WarningsSummaryUseCase"]
