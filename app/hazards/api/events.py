import uuid
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query

from app.deps.repository import get_repo
from app.hazards.repos.hazard_event import HazardEventRepo
from app.hazards.schemas.events import EventFeature, EventFeatureCollection
from app.hazards.use_cases.list_events import GetEventUseCase, ListEventsUseCase

router = APIRouter(prefix="/events", tags=["Events"])

HazardType = Literal["wildfire", "earthquake", "weather_warning"]
Source = Literal["effis", "ign", "aemet"]


@router.get("", response_model=EventFeatureCollection)
async def list_events(
    repo: Annotated[HazardEventRepo, Depends(get_repo(HazardEventRepo))],
    bbox: Annotated[str | None, Query(description="minLon,minLat,maxLon,maxLat (WGS84)")] = None,
    hazard_type: Annotated[list[HazardType] | None, Query()] = None,
    source: Annotated[Source | None, Query()] = None,
    severity_min: Annotated[int | None, Query(ge=1, le=4)] = None,
    starts_after: Annotated[datetime | None, Query()] = None,
    starts_before: Annotated[datetime | None, Query()] = None,
    active: Annotated[bool | None, Query(description="only events in force now")] = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
    cursor: Annotated[str | None, Query()] = None,
):
    use_case = ListEventsUseCase(repo=repo)
    return await use_case.execute(
        bbox_raw=bbox,
        hazard_types=list(hazard_type) if hazard_type else None,
        source=source,
        severity_min=severity_min,
        starts_after=starts_after,
        starts_before=starts_before,
        active=active,
        limit=limit,
        cursor_raw=cursor,
    )


@router.get("/{event_id}", response_model=EventFeature)
async def get_event(
    event_id: uuid.UUID,
    repo: Annotated[HazardEventRepo, Depends(get_repo(HazardEventRepo))],
):
    use_case = GetEventUseCase(repo=repo)
    return await use_case.execute(event_id=event_id)
