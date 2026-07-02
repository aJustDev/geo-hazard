from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

# Tipos canonicos NUESTROS: el adaptador de cada driver mapea el vocabulario
# de la fuente (nombres de campos del WFS) a esto, y el resto del sistema no
# sabe como habla EFFIS.

KIND_HOTSPOT = "hotspot"
KIND_BURNT_AREA = "burnt_area"


@dataclass(frozen=True, slots=True)
class EffisRecord:
    """Un registro de incendio ya normalizado.

    `geometry` es un mapping GeoJSON (coordenadas lon, lat); `attrs` conserva
    los campos crudos de la fuente que valgan la pena.
    """

    external_id: str
    kind: str  # KIND_HOTSPOT | KIND_BURNT_AREA
    geometry: dict[str, Any]
    observed_at: datetime
    area_ha: float | None = None
    attrs: dict[str, Any] = field(default_factory=dict)


__all__ = ["KIND_BURNT_AREA", "KIND_HOTSPOT", "EffisRecord"]
