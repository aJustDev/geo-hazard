from dataclasses import dataclass

from app.analytics.concurrency import run_analytics
from app.analytics.paths import source_snapshot
from app.analytics.queries.earthquakes import frequency_by_month
from app.analytics.schemas.earthquakes import EarthquakeFrequencyResponse, EarthquakeFrequencyRow
from app.core.attribution import attributions_for

_ATTRIBUTION = attributions_for(["ign"])


@dataclass(slots=True)
class EarthquakeFrequencyUseCase:
    """Histograma mensual de sismos desde el snapshot GeoParquet del IGN."""

    async def execute(
        self, *, year: int, min_magnitude: float | None
    ) -> EarthquakeFrequencyResponse:
        snapshot = source_snapshot("ign")
        if not snapshot.exists():
            return EarthquakeFrequencyResponse(
                year=year, min_magnitude=min_magnitude, rows=[], attribution=_ATTRIBUTION
            )
        rows = await run_analytics(
            frequency_by_month, snapshot=str(snapshot), year=year, min_magnitude=min_magnitude
        )
        return EarthquakeFrequencyResponse(
            year=year,
            min_magnitude=min_magnitude,
            rows=[EarthquakeFrequencyRow(**row) for row in rows],
            attribution=_ATTRIBUTION,
        )


__all__ = ["EarthquakeFrequencyUseCase"]
