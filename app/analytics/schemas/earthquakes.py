from app.core.schema import BaseSchema


class EarthquakeFrequencyRow(BaseSchema):
    month: int
    events: int
    max_magnitude: float


class EarthquakeFrequencyResponse(BaseSchema):
    year: int
    min_magnitude: float | None
    rows: list[EarthquakeFrequencyRow]


__all__ = ["EarthquakeFrequencyResponse", "EarthquakeFrequencyRow"]
