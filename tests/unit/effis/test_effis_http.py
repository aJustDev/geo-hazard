from pathlib import Path

import httpx
import pytest

from app.core.config import settings
from app.core.effis.drivers.http import BURNT_AREAS_LAYER, HOTSPOTS_LAYER, EffisHttpClient
from app.core.effis.exceptions import EffisProtocolError, EffisTransientError

FIXTURES = Path(__file__).parents[2] / "fixtures" / "effis"


BBOX = "-31,27,5,44"


def _client(handler) -> EffisHttpClient:
    return EffisHttpClient(bbox=BBOX, transport=httpx.MockTransport(handler))


async def test_burnt_areas_ok_devuelve_registros() -> None:
    seen: dict[str, httpx.URL] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = request.url
        return httpx.Response(
            200, content=(FIXTURES / "nrt_ba_poly_week_iberia.geojson").read_bytes()
        )

    records = await _client(handler).fetch_burnt_areas()

    assert len(records) == 84
    assert seen["url"].params["typename"] == BURNT_AREAS_LAYER
    assert seen["url"].params["outputFormat"] == "geojson"
    # El rectangulo viene de configuracion (EFFIS_BBOX), no del codigo.
    assert seen["url"].params["bbox"] == BBOX


async def test_hotspots_ok_devuelve_registros() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["typename"] == HOTSPOTS_LAYER
        return httpx.Response(200, content=(FIXTURES / "all_hs_week_iberia.geojson").read_bytes())

    records = await _client(handler).fetch_hotspots()

    assert len(records) == 40


async def test_5xx_es_transitorio() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(502)

    with pytest.raises(EffisTransientError, match="502"):
        await _client(handler).fetch_burnt_areas()


async def test_error_de_red_es_transitorio() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("el server colgado, como en el spike")

    with pytest.raises(EffisTransientError, match="unreachable"):
        await _client(handler).fetch_hotspots()


async def test_4xx_es_error_de_protocolo() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    with pytest.raises(EffisProtocolError, match="404"):
        await _client(handler).fetch_burnt_areas()


async def test_excepcion_xml_de_mapserver_es_transitoria() -> None:
    # MapServer responde 200 con ServiceExceptionReport cuando el backend de
    # la capa falla (msPostGISLayerGetItems, observado durante dias en el
    # mapfile /effis): fallo de servidor reintentable, no cambio de contrato.
    body = (
        b'<?xml version="1.0" encoding="UTF-8"?>'
        b'<ServiceExceptionReport version="1.2.0">'
        b"<ServiceException>msPostGISLayerGetItems(): Query error</ServiceException>"
        b"</ServiceExceptionReport>"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body)

    with pytest.raises(EffisTransientError, match="layer backend"):
        await _client(handler).fetch_burnt_areas()


async def test_capa_inexistente_es_error_de_protocolo() -> None:
    # Respuesta real de gwis al pedir all.hs.week tras su renombrado
    # (2026-11-02): mismo 200 + ServiceExceptionReport, pero reintentar no lo
    # arregla. Como transitorio, la caida paso 5 dias por "fuente no
    # disponible" y el contract test se saltaba.
    body = (
        b"<?xml version='1.0' encoding=\"UTF-8\" ?>"
        b'<ServiceExceptionReport version="1.2.0">'
        b'<ServiceException code="InvalidParameterValue" locator="typename">'
        b"msWFSGetFeature(): WFS server error. TYPENAME &#39;all.hs.week&#39; doesn&#39;t"
        b" exist in this server.  Please check the capabilities and reformulate your request."
        b"</ServiceException>"
        b"</ServiceExceptionReport>"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body)

    with pytest.raises(EffisProtocolError, match="rejected the request"):
        await _client(handler).fetch_hotspots()


async def test_respuesta_gigante_se_corta(monkeypatch: pytest.MonkeyPatch) -> None:
    # C3 (ADR-0017): un cuerpo mayor que el tope se corta por streaming y se
    # trata como transitorio, en vez de materializarse entero en RAM.
    monkeypatch.setattr(settings, "HTTP_MAX_RESPONSE_BYTES", 16)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"x" * 4096)

    with pytest.raises(EffisTransientError, match="too large"):
        await _client(handler).fetch_burnt_areas()
