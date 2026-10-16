import pytest

from app.core.aemet.drivers.http import AemetHttpClient
from app.core.aemet.exceptions import AemetTransientError
from app.core.config import settings

pytestmark = pytest.mark.contract


async def test_ultimo_boletin_cap_de_aemet() -> None:
    if not settings.AEMET_API_KEY:
        pytest.skip("sin AEMET_API_KEY")
    try:
        warnings = await AemetHttpClient(api_key=settings.AEMET_API_KEY).fetch_warnings()
    except AemetTransientError as exc:
        pytest.skip(f"AEMET no disponible: {exc}")

    # El boletin nacional trae avisos de todos los niveles (verdes incluidos):
    # vacio indicaria un cambio en el empaquetado.
    assert warnings
    for w in warnings:
        assert w.external_id
        assert w.msg_type in {"Alert", "Update", "Cancel"}
        assert w.sent.tzinfo is not None
        if w.polygon:
            # CAP: pares "lat,lon". Solo Espana (Canarias incluidas): un par
            # fuera de rango delata un cambio en el orden de ejes.
            for pair in w.polygon.split():
                lat, lon = (float(v) for v in pair.split(","))
                assert 26 <= lat <= 45, pair
                assert -19 <= lon <= 6, pair
