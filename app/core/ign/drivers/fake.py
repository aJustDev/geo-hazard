from datetime import UTC, datetime

from app.core.ign.types import IgnRecord


def _default_records() -> list[IgnRecord]:
    # Dos sismos sinteticos pero verosimiles: uno peninsular (Golfo de Cadiz,
    # zona sismica real) y otro en Canarias, para que los tests de bbox
    # tengan algo que dejar fuera.
    return [
        IgnRecord(
            external_id="fake-eq-1",
            magnitude=3.5,
            region="GOLFO DE CADIZ",
            latitude=36.6366,
            longitude=-8.0798,
            occurred_at=datetime(2026, 7, 2, 5, 6, 37, tzinfo=UTC),
            attrs={"raw_local_moment": "02/07/2026 7:06:37"},
        ),
        IgnRecord(
            external_id="fake-eq-2",
            magnitude=2.6,
            region="ATLANTICO-CANARIAS",
            latitude=28.0292,
            longitude=-16.2073,
            occurred_at=datetime(2026, 6, 25, 2, 50, 1, tzinfo=UTC),
        ),
    ]


class IgnFakeClient:
    """Driver sin red para dev y tests. Cumple el Protocol IgnClient."""

    def __init__(self, *, earthquakes: list[IgnRecord] | None = None) -> None:
        self._earthquakes = earthquakes if earthquakes is not None else _default_records()

    async def fetch_earthquakes(self) -> list[IgnRecord]:
        return list(self._earthquakes)


__all__ = ["IgnFakeClient"]
