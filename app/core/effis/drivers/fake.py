from datetime import UTC, datetime

from app.core.effis.types import KIND_BURNT_AREA, KIND_HOTSPOT, EffisRecord


def _default_records() -> list[EffisRecord]:
    # Dos registros sinteticos pero verosimiles sobre la peninsula: un hotspot
    # VIIRS puntual y un area quemada poligonal en la Siberia extremena.
    observed = datetime(2026, 7, 1, 13, 30, tzinfo=UTC)
    return [
        EffisRecord(
            external_id="fake-hs-1",
            kind=KIND_HOTSPOT,
            geometry={"type": "Point", "coordinates": [-5.1, 39.2]},
            observed_at=observed,
            attrs={"sensor": "VIIRS", "frp": 12.5},
        ),
        EffisRecord(
            external_id="fake-ba-1",
            kind=KIND_BURNT_AREA,
            geometry={
                "type": "Polygon",
                "coordinates": [
                    [[-5.20, 39.10], [-5.10, 39.10], [-5.10, 39.20], [-5.20, 39.20], [-5.20, 39.10]]
                ],
            },
            observed_at=observed,
            area_ha=820.0,
            attrs={"product": "effis.nrt.ba"},
        ),
    ]


class EffisFakeClient:
    """Driver sin red para dev y tests. Cumple el Protocol EffisClient."""

    def __init__(
        self,
        *,
        hotspots: list[EffisRecord] | None = None,
        burnt_areas: list[EffisRecord] | None = None,
    ) -> None:
        defaults = _default_records()
        self._hotspots = hotspots if hotspots is not None else [defaults[0]]
        self._burnt_areas = burnt_areas if burnt_areas is not None else [defaults[1]]

    async def fetch_hotspots(self) -> list[EffisRecord]:
        return list(self._hotspots)

    async def fetch_burnt_areas(self) -> list[EffisRecord]:
        return list(self._burnt_areas)


__all__ = ["EffisFakeClient"]
