"""Normalizacion de severidad a la escala ordinal comun 1-4 (ADR-0009).

Servicio puro. La escala es con perdida y opinable: el valor crudo de cada
fuente se conserva siempre en `attrs`; estas funciones solo alimentan el
filtro transversal `severity_min` de la API.
"""

# Umbrales de area quemada (hectareas). EFFIS cartografia incendios de ~30 ha
# o mas, asi que el suelo practico de un poligono ba es ya "relevante".
_BURNT_AREA_THRESHOLDS = ((5000.0, 4), (500.0, 3))

# Niveles Meteoalerta de AEMET. "verde" (sin riesgo) tiene mapeo por
# completitud, pero el use case no ingiere avisos verdes (ADR-0010).
_AEMET_LEVELS = {"verde": 1, "amarillo": 2, "naranja": 3, "rojo": 4}

# Umbrales de magnitud IGN. Anclados a efectos tipicos en la peninsula:
# <3.0 raramente se siente, 3.0-3.9 se siente sin danos, 4.0-5.4 danos
# ligeros posibles, >=5.5 danos estructurales probables.
_IGN_MAGNITUDE_THRESHOLDS = ((5.5, 4), (4.0, 3), (3.0, 2))


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


def ign_severity(*, magnitude: float) -> int:
    """Severidad de un sismo IGN por magnitud."""
    for threshold, level in _IGN_MAGNITUDE_THRESHOLDS:
        if magnitude >= threshold:
            return level
    return 1


def aemet_severity(*, nivel: str) -> int:
    """Severidad de un aviso AEMET por su parametro "AEMET-Meteoalerta nivel"."""
    try:
        return _AEMET_LEVELS[nivel.strip().lower()]
    except KeyError:
        raise ValueError(f"unknown AEMET warning level: {nivel!r}") from None


__all__ = ["aemet_severity", "effis_severity", "ign_severity"]
