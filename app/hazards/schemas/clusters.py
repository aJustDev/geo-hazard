from datetime import datetime
from typing import Any, Literal

from app.core.schema import BaseSchema


class ClusterProperties(BaseSchema):
    cluster_id: int
    count: int
    max_severity: int
    first_starts_at: datetime
    last_starts_at: datetime


class ClusterFeature(BaseSchema):
    """Un cluster DBSCAN resumido: su geometria es el centroide (Point 4326),
    calculado en 25830 para que sea el centroide metrico real (ADR-0011)."""

    type: Literal["Feature"] = "Feature"
    geometry: dict[str, Any]
    properties: ClusterProperties


class ClusterFeatureCollection(BaseSchema):
    type: Literal["FeatureCollection"] = "FeatureCollection"
    features: list[ClusterFeature]
    numberReturned: int  # noqa: N815


__all__ = ["ClusterFeature", "ClusterFeatureCollection", "ClusterProperties"]
