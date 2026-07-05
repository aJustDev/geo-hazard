from pathlib import Path

import httpx
import pytest

from app.core.config import settings
from app.core.ign.drivers.http import FEED_URL, IgnHttpClient
from app.core.ign.exceptions import IgnProtocolError, IgnTransientError

FIXTURE = Path(__file__).parents[2] / "fixtures" / "ign" / "georss_ultimos_10_dias.xml"


def _client(handler) -> IgnHttpClient:
    return IgnHttpClient(transport=httpx.MockTransport(handler))


async def test_feed_ok_devuelve_registros() -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        return httpx.Response(200, content=FIXTURE.read_bytes())

    records = await _client(handler).fetch_earthquakes()

    assert seen["url"] == FEED_URL
    assert len(records) == 14


async def test_5xx_es_transitorio() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    with pytest.raises(IgnTransientError, match="503"):
        await _client(handler).fetch_earthquakes()


async def test_error_de_red_es_transitorio() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("dns caido")

    with pytest.raises(IgnTransientError, match="unreachable"):
        await _client(handler).fetch_earthquakes()


async def test_4xx_es_error_de_protocolo() -> None:
    # Un 404 no se arregla reintentando: la URL del feed cambio.
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    with pytest.raises(IgnProtocolError, match="404"):
        await _client(handler).fetch_earthquakes()


async def test_respuesta_gigante_se_corta(monkeypatch: pytest.MonkeyPatch) -> None:
    # C3 (ADR-0017): el feed se lee por streaming con tope de bytes.
    monkeypatch.setattr(settings, "HTTP_MAX_RESPONSE_BYTES", 16)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"x" * 4096)

    with pytest.raises(IgnTransientError, match="too large"):
        await _client(handler).fetch_earthquakes()
