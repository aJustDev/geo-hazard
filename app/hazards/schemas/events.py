import uuid
from datetime import datetime
from typing import Any, Literal

from app.core.schema import BaseSchema


class EventProperties(BaseSchema):
    source: str
    hazard_type: str
    severity: int
    starts_at: datetime
    ends_at: datetime | None
    external_id: str
    # attrs anidado tal cual: aplanarlo mezclaria los espacios de nombres de
    # tres fuentes distintas en un mismo nivel.
    attrs: dict[str, Any]


class EventFeature(BaseSchema):
    type: Literal["Feature"] = "Feature"
    id: uuid.UUID
    geometry: dict[str, Any]
    properties: EventProperties


class EventFeatureCollection(BaseSchema):
    """FeatureCollection RFC 7946. numberReturned y nextCursor son foreign
    members, permitidos por la seccion 6.1 de la RFC (ADR-0006)."""

    type: Literal["FeatureCollection"] = "FeatureCollection"
    features: list[EventFeature]
    # camelCase intencionado: son foreign members del GeoJSON, no campos Python.
    numberReturned: int  # noqa: N815
    nextCursor: str | None = None  # noqa: N815


__all__ = [
    "EventFeature",
    "EventFeatureCollection",
    "EventProperties",
]
