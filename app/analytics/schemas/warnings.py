from app.core.schema import BaseSchema


class WarningsSummaryRow(BaseSchema):
    phenomenon: str
    level: str
    warnings: int
    zones: int


class WarningsSummaryResponse(BaseSchema):
    year: int
    rows: list[WarningsSummaryRow]


__all__ = ["WarningsSummaryResponse", "WarningsSummaryRow"]
