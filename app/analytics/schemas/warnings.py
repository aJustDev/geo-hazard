from app.core.attribution import SourceAttribution
from app.core.schema import BaseSchema


class WarningsSummaryRow(BaseSchema):
    phenomenon: str
    level: str
    warnings: int
    zones: int


class WarningsSummaryResponse(BaseSchema):
    year: int
    rows: list[WarningsSummaryRow]
    # Atribucion exigida por las licencias del dato agregado (NOTICE).
    attribution: list[SourceAttribution]


__all__ = ["WarningsSummaryResponse", "WarningsSummaryRow"]
