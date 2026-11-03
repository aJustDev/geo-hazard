from datetime import date

from pydantic import Field

from app.core.attribution import SourceAttribution
from app.core.schema import BaseSchema

# JSON plano, no GeoJSON: son agregados sin geometria (ADR-0012).


class ZoneMetrics(BaseSchema):
    """Dias con aviso por su peor nivel (ADR-0023), sismos y areas quemadas."""

    warning_days_yellow: int = Field(description="Days whose worst warning was yellow.")
    warning_days_orange: int = Field(description="Days whose worst warning was orange.")
    warning_days_red: int = Field(description="Days whose worst warning was red.")
    earthquakes: int
    max_magnitude: float | None
    burnt_areas: int = Field(description="EFFIS burnt-area polygons (hotspots excluded).")
    burned_area_ha: float


class ZoneMonthRow(ZoneMetrics):
    month: int


class ZoneSpec(BaseSchema):
    province: str | None = None
    lon: float | None = None
    lat: float | None = None
    radius_m: float | None = None


class ZoneMonthlyResponse(BaseSchema):
    year: int
    zone: ZoneSpec
    history_since: date | None = Field(
        description="First civil day with data from every source; earlier zeros mean no data."
    )
    rows: list[ZoneMonthRow]
    # Atribucion exigida por las licencias del dato agregado (NOTICE).
    attribution: list[SourceAttribution]


class ProvinceSummaryRow(ZoneMetrics):
    province_code: str
    province: str


class ProvincesSummaryResponse(BaseSchema):
    year: int
    history_since: date | None
    rows: list[ProvinceSummaryRow]
    attribution: list[SourceAttribution]


__all__ = [
    "ProvinceSummaryRow",
    "ProvincesSummaryResponse",
    "ZoneMonthRow",
    "ZoneMonthlyResponse",
    "ZoneSpec",
]
