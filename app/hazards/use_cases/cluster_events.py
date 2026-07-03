from dataclasses import dataclass
from datetime import datetime

from app.hazards.repos.hazard_event import HazardEventRepo
from app.hazards.schemas.clusters import (
    ClusterFeature,
    ClusterFeatureCollection,
    ClusterProperties,
)
from app.hazards.services.geometry import wkb_to_geojson


@dataclass(slots=True)
class ClusterEventsUseCase:
    """Clusters DBSCAN de eventos como FeatureCollection de centroides."""

    repo: HazardEventRepo

    async def execute(
        self,
        *,
        eps_m: float,
        min_points: int,
        hazard_types: list[str] | None = None,
        source: str | None = None,
        severity_min: int | None = None,
        starts_after: datetime | None = None,
        starts_before: datetime | None = None,
        active: bool | None = None,
    ) -> ClusterFeatureCollection:
        rows = await self.repo.cluster_rows(
            eps_m=eps_m,
            min_points=min_points,
            hazard_types=hazard_types,
            source=source,
            severity_min=severity_min,
            starts_after=starts_after,
            starts_before=starts_before,
            active=active,
        )
        features = [
            ClusterFeature(
                geometry=wkb_to_geojson(row["centroid"]),
                properties=ClusterProperties(
                    cluster_id=row["cluster_id"],
                    count=row["count"],
                    max_severity=row["max_severity"],
                    first_starts_at=row["first_starts_at"],
                    last_starts_at=row["last_starts_at"],
                ),
            )
            for row in rows
        ]
        return ClusterFeatureCollection(features=features, numberReturned=len(features))


__all__ = ["ClusterEventsUseCase"]
