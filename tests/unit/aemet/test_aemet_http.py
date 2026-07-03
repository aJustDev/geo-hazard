import io
import json
import tarfile
from pathlib import Path

import httpx
import pytest

from app.core.aemet.drivers.http import LAST_BULLETIN_URL, AemetHttpClient
from app.core.aemet.exceptions import AemetProtocolError, AemetTransientError

FIXTURE = Path(__file__).parents[2] / "fixtures" / "aemet" / "cap_aviso_naranja_ta.xml"

DATOS_URL = "https://opendata.aemet.es/opendata/sh/tar-de-prueba"


def _tar_with_caps(count: int = 1) -> bytes:
    """Tar en memoria con N copias del CAP real, como el que sirve AEMET."""
    payload = FIXTURE.read_bytes()
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as archive:
        for i in range(count):
            info = tarfile.TarInfo(name=f"Z_CAP_{i}.xml")
            info.size = len(payload)
            archive.addfile(info, io.BytesIO(payload))
    return buffer.getvalue()


def _envelope(estado: int = 200, datos: str | None = DATOS_URL) -> str:
    return json.dumps({"descripcion": "exito", "estado": estado, "datos": datos})


def _client(handler) -> AemetHttpClient:
    return AemetHttpClient(api_key="clave-de-prueba", transport=httpx.MockTransport(handler))


async def test_flujo_de_dos_saltos_completo() -> None:
    seen: dict[str, httpx.Request] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == LAST_BULLETIN_URL:
            seen["primero"] = request
            return httpx.Response(200, text=_envelope())
        seen["segundo"] = request
        return httpx.Response(200, content=_tar_with_caps(count=3))

    warnings = await _client(handler).fetch_warnings()

    assert len(warnings) == 3
    assert warnings[0].level == "naranja"
    # La key viaja SOLO en la cabecera del primer salto.
    assert seen["primero"].headers["api_key"] == "clave-de-prueba"
    assert "api_key" not in seen["segundo"].headers
    assert str(seen["segundo"].url) == DATOS_URL


async def test_cuota_agotada_es_transitorio() -> None:
    # AEMET codifica el estado DENTRO del sobre JSON, no en el status HTTP.
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=_envelope(estado=429, datos=None))

    with pytest.raises(AemetTransientError, match="quota"):
        await _client(handler).fetch_warnings()


async def test_key_rechazada_es_error_de_protocolo() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=json.dumps({"estado": 401, "descripcion": "no valido"}))

    with pytest.raises(AemetProtocolError, match="401"):
        await _client(handler).fetch_warnings()


async def test_5xx_es_transitorio() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    with pytest.raises(AemetTransientError, match="503"):
        await _client(handler).fetch_warnings()


async def test_sobre_no_json_es_error_de_protocolo() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>mantenimiento</html>")

    with pytest.raises(AemetProtocolError, match="not JSON"):
        await _client(handler).fetch_warnings()


async def test_datos_caducados_es_transitorio() -> None:
    # La URL temporal expira: el siguiente poll pedira una fresca.
    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == LAST_BULLETIN_URL:
            return httpx.Response(200, text=_envelope())
        return httpx.Response(404)

    with pytest.raises(AemetTransientError, match="404"):
        await _client(handler).fetch_warnings()


async def test_datos_que_no_son_tar_es_error_de_protocolo() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == LAST_BULLETIN_URL:
            return httpx.Response(200, text=_envelope())
        return httpx.Response(200, content=b"esto no es un tar")

    with pytest.raises(AemetProtocolError, match="tar"):
        await _client(handler).fetch_warnings()
