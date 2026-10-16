from app.core.attribution import SourceAttribution
from app.core.schema import BaseSchema


class EarthquakeFrequencyRow(BaseSchema):
    month: int
    events: int
    max_magnitude: float


class EarthquakeFrequencyResponse(BaseSchema):
    year: int
    min_magnitude: float | None
    rows: list[EarthquakeFrequencyRow]
    # Atribucion exigida por las licencias del dato agregado (NOTICE).
    attribution: list[SourceAttribution]


__all__ = ["EarthquakeFrequencyResponse", "EarthquakeFrequencyRow"]
