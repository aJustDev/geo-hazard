from typing import Annotated

from fastapi import APIRouter, Query, Request, Response

from app.analytics.schemas.earthquakes import EarthquakeFrequencyResponse
from app.analytics.schemas.warnings import WarningsSummaryResponse
from app.analytics.schemas.wildfires import BurnedAreaResponse
from app.analytics.use_cases.burned_area import BurnedAreaUseCase
from app.analytics.use_cases.earthquake_frequency import EarthquakeFrequencyUseCase
from app.analytics.use_cases.warnings_summary import WarningsSummaryUseCase
from app.core.rate_limit import EXPENSIVE_LIMIT, limiter
from app.core.schema import error_responses

# Sin Depends(get_session): este plano no toca Postgres (ADR-0012).
router = APIRouter(prefix="/analytics", tags=["Analytics"])

Year = Annotated[int, Query(ge=2000, le=2100)]
# Todo el plano comparte cuota estricta y semaforo de concurrencia (ADR-0017).
_ERRORS = error_responses(422, 503)
_NOTE = (
    " Computed by DuckDB over the GeoParquet history. Stricter rate limit than "
    "the rest of the API; 503 with Retry-After when the analytics plane is saturated."
)


@router.get(
    "/wildfires/burned-area",
    response_model=BurnedAreaResponse,
    summary="Burned area by province and month",
    description="Hectares of EFFIS burnt-area polygons per Spanish province (INE code) and month."
    + _NOTE,
    responses=_ERRORS,
)
@limiter.limit(EXPENSIVE_LIMIT)
async def burned_area(
    request: Request,
    # slowapi (headers_enabled=True) inyecta X-RateLimit-* en este `response`;
    # sin el parametro el decorador @limiter.limit lanza y la ruta da 500.
    response: Response,
    year: Year,
    province: Annotated[
        str | None, Query(pattern=r"^\d{2}$", description="INE province code, e.g. 06")
    ] = None,
):
    use_case = BurnedAreaUseCase()
    return await use_case.execute(year=year, province_code=province)


@router.get(
    "/earthquakes/frequency",
    response_model=EarthquakeFrequencyResponse,
    summary="Earthquake frequency by month",
    description="IGN earthquakes and maximum magnitude per month, optionally above `min_magnitude`."
    + _NOTE,
    responses=_ERRORS,
)
@limiter.limit(EXPENSIVE_LIMIT)
async def earthquake_frequency(
    request: Request,
    response: Response,
    year: Year,
    min_magnitude: Annotated[float | None, Query(ge=0, le=10)] = None,
):
    use_case = EarthquakeFrequencyUseCase()
    return await use_case.execute(year=year, min_magnitude=min_magnitude)


@router.get(
    "/warnings/summary",
    response_model=WarningsSummaryResponse,
    summary="Weather warnings by phenomenon and level",
    description="AEMET warnings per Meteoalerta phenomenon and level, with the number of "
    "distinct zones affected." + _NOTE,
    responses=_ERRORS,
)
@limiter.limit(EXPENSIVE_LIMIT)
async def warnings_summary(
    request: Request,
    response: Response,
    year: Year,
    phenomenon: Annotated[
        str | None, Query(pattern=r"^[A-Z]{2}$", description="Meteoalerta code, e.g. AT")
    ] = None,
):
    use_case = WarningsSummaryUseCase()
    return await use_case.execute(year=year, phenomenon_code=phenomenon)


__all__ = ["router"]
