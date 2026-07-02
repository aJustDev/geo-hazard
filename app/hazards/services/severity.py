"""Normalizacion de severidad a la escala ordinal comun 1-4 (ADR-0009).

Servicio puro. La escala es con perdida y opinable: el valor crudo de cada
fuente se conserva siempre en `attrs`; esta funcion solo alimenta el filtro
transversal `severity_min` de la API. En esta fase solo existe EFFIS; IGN y
AEMET anaden aqui sus mapas en la fase 3.
"""

# Umbrales de area quemada (hectareas). EFFIS cartografia incendios de ~30 ha
# o mas, asi que el suelo practico de un poligono ba es ya "relevante".
_BURNT_AREA_THRESHOLDS = ((5000.0, 4), (500.0, 3))


def effis_severity(*, kind: str, area_ha: float | None = None) -> int:
    """Severidad de un registro EFFIS.

    Un hotspot (deteccion satelital puntual) es actividad confirmada pero sin
    extension conocida: 2 fijo. Un area quemada escala por hectareas.
    """
    if kind == "hotspot":
        return 2
    if kind == "burnt_area":
        if area_ha is None:
            return 2
        for threshold, level in _BURNT_AREA_THRESHOLDS:
            if area_ha >= threshold:
                return level
        return 2
    raise ValueError(f"unknown EFFIS record kind: {kind!r}")


__all__ = ["effis_severity"]
