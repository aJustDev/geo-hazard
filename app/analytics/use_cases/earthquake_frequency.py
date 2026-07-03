from dataclasses import dataclass

from app.analytics.paths import source_snapshot
from app.analytics.queries.earthquakes import frequency_by_month
from app.analytics.schemas.earthquakes import EarthquakeFrequencyResponse, EarthquakeFrequencyRow
from app.core.concurrency import run_blocking


@dataclass(slots=True)
class EarthquakeFrequencyUseCase:
    """Histograma mensual de sismos desde el snapshot GeoParquet del IGN."""

    async def execute(
        self, *, year: int, min_magnitude: float | None
    ) -> EarthquakeFrequencyResponse:
        snapshot = source_snapshot("ign")
        if not snapshot.exists():
            return EarthquakeFrequencyResponse(year=year, min_magnitude=min_magnitude, rows=[])
        rows = await run_blocking(
            frequency_by_month, snapshot=str(snapshot), year=year, min_magnitude=min_magnitude
        )
        return EarthquakeFrequencyResponse(
            year=year,
            min_magnitude=min_magnitude,
            rows=[EarthquakeFrequencyRow(**row) for row in rows],
        )


__all__ = ["EarthquakeFrequencyUseCase"]
