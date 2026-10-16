import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import ConfigDict, Field

from app.core.attribution import SourceAttribution
from app.core.schema import BaseSchema


class EventProperties(BaseSchema):
    source: str = Field(description="Upstream source: effis, ign or aemet.")
    hazard_type: str = Field(description="wildfire, earthquake or weather_warning.")
    severity: int = Field(
        description=(
            "Common ordinal scale across sources, 1 (minor) to 4 (extreme). Lossy by "
            "design; the raw source value is kept in attrs."
        )
    )
    starts_at: datetime = Field(description="Start (UTC): detection, origin time or onset.")
    ends_at: datetime | None = Field(description="End (UTC); null while the event is open-ended.")
    external_id: str = Field(description="Stable identifier in the upstream catalog.")
    # attrs anidado tal cual: aplanarlo mezclaria los espacios de nombres de
    # tres fuentes distintas en un mismo nivel.
    attrs: dict[str, Any] = Field(description="Source-specific raw attributes, as published.")


class EventFeature(BaseSchema):
    type: Literal["Feature"] = "Feature"
    id: uuid.UUID
    geometry: dict[str, Any]
    properties: EventProperties


class EventFeatureCollection(BaseSchema):
    """FeatureCollection RFC 7946. numberReturned y nextCursor son foreign
    members, permitidos por la seccion 6.1 de la RFC (ADR-0006)."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "type": "FeatureCollection",
                    "features": [
                        {
                            "type": "Feature",
                            "id": "6b0f5f7e-3a9e-4d0c-9a51-2f7c1d2e8a10",
                            "geometry": {"type": "Point", "coordinates": [-12.2195, 37.01]},
                            "properties": {
                                "source": "ign",
                                "hazard_type": "earthquake",
                                "severity": 2,
                                "starts_at": "2026-10-15T22:57:05Z",
                                "ends_at": "2026-10-15T22:57:05Z",
                                "external_id": "es2026ugjsf",
                                "attrs": {
                                    "magnitude": 3.1,
                                    "region": "AZORES-CABO DE SAN VICENTE",
                                    "raw_local_moment": "16/10/2026 0:57:05",
                                },
                            },
                        }
                    ],
                    "numberReturned": 1,
                    "nextCursor": None,
                    "attribution": [
                        {
                            "source": "ign",
                            "text": "Obra derivada del catalogo de terremotos del IGN, "
                            "CC-BY 4.0 ign.es",
                            "url": "https://www.ign.es/resources/licencia/Condiciones_licenciaUso_IGN.pdf",
                        }
                    ],
                }
            ]
        }
    )

    type: Literal["FeatureCollection"] = "FeatureCollection"
    features: list[EventFeature]
    # camelCase intencionado: son foreign members del GeoJSON, no campos Python.
    numberReturned: int = Field(description="Features in this page.")  # noqa: N815
    nextCursor: str | None = Field(  # noqa: N815
        default=None, description="Opaque cursor for the next page; null on the last one."
    )
    # Atribucion de las fuentes presentes: foreign member (RFC 7946 6.1) que
    # exigen sus licencias al redistribuir dato elaborado (NOTICE).
    attribution: list[SourceAttribution]


class NearEventProperties(EventProperties):
    # Metros desde el punto de consulta; al borde si el evento es poligonal.
    distance_m: float = Field(description="Meters from the query point (to the edge for polygons).")


class NearEventFeature(BaseSchema):
    type: Literal["Feature"] = "Feature"
    id: uuid.UUID
    geometry: dict[str, Any]
    properties: NearEventProperties


class NearEventFeatureCollection(BaseSchema):
    """Sin nextCursor: una consulta de radio devuelve los N mas cercanos,
    no un listado paginable (ADR-0011)."""

    type: Literal["FeatureCollection"] = "FeatureCollection"
    features: list[NearEventFeature]
    numberReturned: int  # noqa: N815
    # Atribucion de las fuentes presentes: foreign member (RFC 7946 6.1) que
    # exigen sus licencias al redistribuir dato elaborado (NOTICE).
    attribution: list[SourceAttribution]


__all__ = [
    "EventFeature",
    "EventFeatureCollection",
    "EventProperties",
    "NearEventFeature",
    "NearEventFeatureCollection",
    "NearEventProperties",
]
