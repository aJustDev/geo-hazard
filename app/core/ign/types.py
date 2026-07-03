from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

# Tipos canonicos NUESTROS: el adaptador del driver mapea el vocabulario del
# GeoRSS del IGN a esto, y el resto del sistema no sabe como habla el IGN.


@dataclass(frozen=True, slots=True)
class IgnRecord:
    """Un sismo del catalogo IGN ya normalizado.

    `occurred_at` llega ya en UTC (la conversion desde la hora local del feed
    es responsabilidad del parser); `attrs` conserva los crudos que valgan la
    pena, incluida la cadena de fecha original.
    """

    external_id: str  # evid estable del catalogo (p.ej. "es2026mvdms")
    magnitude: float
    region: str
    latitude: float
    longitude: float
    occurred_at: datetime
    attrs: dict[str, Any] = field(default_factory=dict)


__all__ = ["IgnRecord"]
