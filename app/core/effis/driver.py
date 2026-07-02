from typing import Protocol, runtime_checkable

from app.core.effis.types import EffisRecord


@runtime_checkable
class EffisClient(Protocol):
    """Puerto del catalogo de incendios EFFIS.

    Dos productos con semantica distinta: hotspots (detecciones satelitales
    puntuales, ventana rodante de dias) y areas quemadas near-real-time
    (poligonos que crecen mientras el incendio sigue activo).
    """

    async def fetch_hotspots(self) -> list[EffisRecord]: ...

    async def fetch_burnt_areas(self) -> list[EffisRecord]: ...


__all__ = ["EffisClient"]
