from typing import Annotated

from fastapi import APIRouter, Query

from app.analytics.schemas.earthquakes import EarthquakeFrequencyResponse
from app.analytics.schemas.warnings import WarningsSummaryResponse
from app.analytics.schemas.wildfires import BurnedAreaResponse
from app.analytics.use_cases.burned_area import BurnedAreaUseCase
from app.analytics.use_cases.earthquake_frequency import EarthquakeFrequencyUseCase
from app.analytics.use_cases.warnings_summary import WarningsSummaryUseCase

# Sin Depends(get_session): este plano no toca Postgres (ADR-0012).
router = APIRouter(prefix="/analytics", tags=["Analytics"])

Year = Annotated[int, Query(ge=2000, le=2100)]


@router.get("/wildfires/burned-area", response_model=BurnedAreaResponse)
async def burned_area(
    year: Year,
    province: Annotated[
        str | None, Query(pattern=r"^\d{2}$", description="INE province code, e.g. 06")
    ] = None,
):
    use_case = BurnedAreaUseCase()
    return await use_case.execute(year=year, province_code=province)


@router.get("/earthquakes/frequency", response_model=EarthquakeFrequencyResponse)
async def earthquake_frequency(
    year: Year,
    min_magnitude: Annotated[float | None, Query(ge=0, le=10)] = None,
):
    use_case = EarthquakeFrequencyUseCase()
    return await use_case.execute(year=year, min_magnitude=min_magnitude)


@router.get("/warnings/summary", response_model=WarningsSummaryResponse)
async def warnings_summary(
    year: Year,
    phenomenon: Annotated[
        str | None, Query(pattern=r"^[A-Z]{2}$", description="Meteoalerta code, e.g. AT")
    ] = None,
):
    use_case = WarningsSummaryUseCase()
    return await use_case.execute(year=year, phenomenon_code=phenomenon)


__all__ = ["router"]
