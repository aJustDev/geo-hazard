import pytest
import shapely

from app.core.config import settings
from app.core.effis.drivers.http import EffisHttpClient
from app.core.effis.exceptions import EffisTransientError
from app.core.effis.types import KIND_BURNT_AREA, KIND_HOTSPOT, EffisRecord

pytestmark = pytest.mark.contract

# Rectangulo pedido a EFFIS ampliado 1 grado: los centroides deben caer dentro.
# Un centroide fuera delata un cambio en el orden de ejes (ADR-0015).
_AREA = shapely.box(*(float(v) for v in settings.EFFIS_BBOX.split(","))).buffer(1)


def _check(records: list[EffisRecord], kind: str) -> None:
    for r in records:
        assert r.external_id
        assert r.kind == kind
        assert r.observed_at.tzinfo is not None
        geom = shapely.geometry.shape(r.geometry)
        assert geom.is_valid or geom.buffer(0).is_valid
        assert _AREA.contains(geom.centroid), (r.external_id, geom.centroid.wkt)


async def test_capas_wfs_de_effis() -> None:
    client = EffisHttpClient(bbox=settings.EFFIS_BBOX)
    try:
        hotspots = await client.fetch_hotspots()
        burnt_areas = await client.fetch_burnt_areas()
    except EffisTransientError as exc:
        pytest.skip(f"EFFIS no disponible: {exc}")

    # Fuera de temporada ambas capas pueden venir vacias: solo se valida lo
    # que llegue.
    _check(hotspots, KIND_HOTSPOT)
    _check(burnt_areas, KIND_BURNT_AREA)
