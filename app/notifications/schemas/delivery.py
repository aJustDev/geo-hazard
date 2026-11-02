"""Lo que el job de entrega lee de la BD, ya desacoplado del ORM (ADR-0021).

Cada entrega lleva en `items` una foto de los eventos casados como GeoJSON
Features: `id` (uuid del evento), `geometry`, y `properties` con `source`,
`hazard_type`, `severity`, `starts_at`, `ends_at`, `external_id` y `attrs`
(los crudos de la fuente). La entrega nunca vuelve a leer hazard_events.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True, slots=True)
class PendingDelivery:
    id: uuid.UUID
    episode_id: uuid.UUID
    reason: str  # "opened" | "escalated"
    severity: int
    items: list[dict[str, Any]]
    item_count: int


@dataclass(frozen=True, slots=True)
class ClaimedSubscription:
    """Suscripcion reclamada para esta ejecucion, con sus entregas pendientes."""

    id: uuid.UUID
    channel: str
    endpoint: str
    credential: str
    hazard_types: list[str]
    area_id: uuid.UUID
    area_label: str
    # retry_at antes del reclamo: se restaura si el presupuesto no llega.
    previous_retry_at: datetime | None
    deliveries: list[PendingDelivery]


__all__ = ["ClaimedSubscription", "PendingDelivery"]
