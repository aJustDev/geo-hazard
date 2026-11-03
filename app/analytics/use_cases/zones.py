from dataclasses import dataclass

from app.analytics.concurrency import run_analytics
from app.analytics.paths import PROVINCES_PARQUET, source_snapshot
from app.analytics.queries.zones import Circle, provinces_summary, zone_monthly
from app.analytics.schemas.zones import (
    ProvincesSummaryResponse,
    ProvinceSummaryRow,
    ZoneMonthlyResponse,
    ZoneMonthRow,
    ZoneSpec,
)
from app.core.attribution import attributions_for
from app.core.exceptions.exceptions import BusinessValidationError

_SOURCES = ("aemet", "ign", "effis")


def _snapshots() -> dict[str, str]:
    """Solo las fuentes con snapshot: una que aun no ha ingerido nada da ceros."""
    return {s: str(path) for s in _SOURCES if (path := source_snapshot(s)).exists()}


@dataclass(slots=True)
class ZoneMonthlyUseCase:
    """Serie mensual de una zona: una provincia o un circulo, no las dos."""

    async def execute(
        self,
        *,
        year: int,
        province: str | None,
        lon: float | None,
        lat: float | None,
        radius_m: float | None,
    ) -> ZoneMonthlyResponse:
        circle_parts = (lon, lat, radius_m)
        has_circle = all(part is not None for part in circle_parts)
        if any(part is not None for part in circle_parts) and not has_circle:
            raise BusinessValidationError("a circle needs lon, lat and radius_m")
        if (province is None) == (not has_circle):
            raise BusinessValidationError("give exactly one zone: province, or lon+lat+radius_m")
        circle = Circle(lon, lat, radius_m) if has_circle else None  # type: ignore[arg-type]

        result = await run_analytics(
            zone_monthly, snapshots=_snapshots(), year=year, province=province, circle=circle
        )
        # La pertenencia a provincia sale de los limites del CNIG.
        sources = [*_SOURCES, *(["cnig"] if province else [])]
        return ZoneMonthlyResponse(
            year=year,
            zone=ZoneSpec(province=province, lon=lon, lat=lat, radius_m=radius_m),
            history_since=result["history_since"],
            rows=[ZoneMonthRow(**row) for row in result["rows"]],
            attribution=attributions_for(sources),
        )


@dataclass(slots=True)
class ProvincesSummaryUseCase:
    """Las metricas del ano por provincia, en una llamada (para la coropleta)."""

    async def execute(self, *, year: int) -> ProvincesSummaryResponse:
        result = await run_analytics(
            provinces_summary,
            snapshots=_snapshots(),
            provinces=str(PROVINCES_PARQUET),
            year=year,
        )
        return ProvincesSummaryResponse(
            year=year,
            history_since=result["history_since"],
            rows=[ProvinceSummaryRow(**row) for row in result["rows"]],
            attribution=attributions_for([*_SOURCES, "cnig"]),
        )


__all__ = ["ProvincesSummaryUseCase", "ZoneMonthlyUseCase"]
