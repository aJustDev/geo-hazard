import uuid
from dataclasses import dataclass
from datetime import datetime

from app.core.exceptions.exceptions import BusinessValidationError, NotFoundError
from app.hazards.models.hazard_event import HazardEventORM
from app.hazards.repos.hazard_event import HazardEventRepo
from app.hazards.schemas.events import EventFeature, EventFeatureCollection, EventProperties
from app.hazards.services.geometry import parse_bbox, wkb_to_geojson
from app.hazards.services.pagination import decode_cursor, encode_cursor


def feature_from_orm(event: HazardEventORM) -> EventFeature:
    """Ensambla el Feature: la geometria sale de WKB SOLO via el servicio."""
    return EventFeature(
        id=event.id,
        geometry=wkb_to_geojson(event.geom),
        properties=EventProperties.model_validate(event),
    )


@dataclass(slots=True)
class ListEventsUseCase:
    repo: HazardEventRepo

    async def execute(
        self,
        *,
        bbox_raw: str | None = None,
        hazard_types: list[str] | None = None,
        source: str | None = None,
        severity_min: int | None = None,
        starts_after: datetime | None = None,
        starts_before: datetime | None = None,
        active: bool | None = None,
        limit: int = 100,
        cursor_raw: str | None = None,
    ) -> EventFeatureCollection:
        bbox = self._parse_bbox(bbox_raw)
        cursor = None
        if cursor_raw is not None:
            try:
                cursor = decode_cursor(cursor_raw)
            except ValueError as exc:
                raise BusinessValidationError("invalid cursor") from exc

        items, next_key = await self.repo.list_page(
            bbox=bbox,
            hazard_types=hazard_types,
            source=source,
            severity_min=severity_min,
            starts_after=starts_after,
            starts_before=starts_before,
            active=active,
            limit=limit,
            cursor=cursor,
        )

        next_cursor = (
            encode_cursor(starts_at=next_key[0], event_id=next_key[1]) if next_key else None
        )
        features = [feature_from_orm(item) for item in items]
        return EventFeatureCollection(
            features=features,
            numberReturned=len(features),
            nextCursor=next_cursor,
        )

    @staticmethod
    def _parse_bbox(bbox_raw: str | None) -> tuple[float, float, float, float] | None:
        """'minLon,minLat,maxLon,maxLat' -> tupla validada. 400 si esta mal."""
        try:
            return parse_bbox(bbox_raw)
        except ValueError as exc:
            raise BusinessValidationError(f"invalid bbox: {exc}") from exc


@dataclass(slots=True)
class GetEventUseCase:
    repo: HazardEventRepo

    async def execute(self, *, event_id: uuid.UUID) -> EventFeature:
        event = await self.repo.get_by_id(event_id)
        if event is None:
            raise NotFoundError("hazard event", event_id)
        return feature_from_orm(event)


__all__ = ["GetEventUseCase", "ListEventsUseCase", "feature_from_orm"]
