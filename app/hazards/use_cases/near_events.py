from dataclasses import dataclass
from datetime import datetime

from app.hazards.repos.hazard_event import HazardEventRepo
from app.hazards.schemas.events import (
    EventProperties,
    NearEventFeature,
    NearEventFeatureCollection,
    NearEventProperties,
)
from app.hazards.services.geometry import wkb_to_geojson


@dataclass(slots=True)
class NearEventsUseCase:
    """Eventos alrededor de un punto, con distance_m en properties.

    La validacion de rangos (lat/lon WGS84, radio <= 200 km) vive en los
    Query params de la API; aqui los valores llegan ya saneados.
    """

    repo: HazardEventRepo

    async def execute(
        self,
        *,
        latitude: float,
        longitude: float,
        radius_m: float,
        hazard_types: list[str] | None = None,
        source: str | None = None,
        severity_min: int | None = None,
        starts_after: datetime | None = None,
        starts_before: datetime | None = None,
        active: bool | None = None,
        limit: int = 100,
    ) -> NearEventFeatureCollection:
        pairs = await self.repo.near_page(
            latitude=latitude,
            longitude=longitude,
            radius_m=radius_m,
            hazard_types=hazard_types,
            source=source,
            severity_min=severity_min,
            starts_after=starts_after,
            starts_before=starts_before,
            active=active,
            limit=limit,
        )
        features = [
            NearEventFeature(
                id=event.id,
                geometry=wkb_to_geojson(event.geom),
                properties=NearEventProperties(
                    **EventProperties.model_validate(event).model_dump(),
                    # Decimetros de precision: mas seria falsa exactitud tras
                    # dos reproyecciones.
                    distance_m=round(distance, 1),
                ),
            )
            for event, distance in pairs
        ]
        return NearEventFeatureCollection(features=features, numberReturned=len(features))


__all__ = ["NearEventsUseCase"]
