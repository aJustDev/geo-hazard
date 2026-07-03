from dataclasses import dataclass

from app.analytics.paths import PROVINCES_PARQUET, source_snapshot
from app.analytics.queries.wildfires import burned_area_by_month
from app.analytics.schemas.wildfires import BurnedAreaResponse, BurnedAreaRow
from app.core.concurrency import run_blocking


@dataclass(slots=True)
class BurnedAreaUseCase:
    """Hectareas quemadas por provincia y mes, desde el snapshot GeoParquet.

    Sin snapshot todavia (ninguna ingesta con cambios) la respuesta es
    vacia, no un error: la pregunta es legitima y la respuesta es "nada".
    """

    async def execute(self, *, year: int, province_code: str | None) -> BurnedAreaResponse:
        snapshot = source_snapshot("effis")
        if not snapshot.exists():
            return BurnedAreaResponse(year=year, rows=[])
        rows = await run_blocking(
            burned_area_by_month,
            snapshot=str(snapshot),
            provinces=str(PROVINCES_PARQUET),
            year=year,
            province_code=province_code,
        )
        return BurnedAreaResponse(year=year, rows=[BurnedAreaRow(**row) for row in rows])


__all__ = ["BurnedAreaUseCase"]
