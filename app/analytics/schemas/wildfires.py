from app.core.attribution import SourceAttribution
from app.core.schema import BaseSchema

# JSON plano, no GeoJSON: son agregados sin geometria (ADR-0012).


class BurnedAreaRow(BaseSchema):
    province_code: str
    province: str
    month: int
    events: int
    burned_area_ha: float


class BurnedAreaResponse(BaseSchema):
    year: int
    rows: list[BurnedAreaRow]
    # Atribucion exigida por las licencias del dato agregado (NOTICE).
    attribution: list[SourceAttribution]


__all__ = ["BurnedAreaResponse", "BurnedAreaRow"]
