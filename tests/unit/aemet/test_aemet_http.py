import io
import json
import tarfile
from pathlib import Path

import httpx
import pytest

from app.core.aemet.drivers import http as aemet_http
from app.core.aemet.drivers.http import LAST_BULLETIN_URL, AemetHttpClient
from app.core.aemet.exceptions import AemetProtocolError, AemetTransientError
from app.core.config import settings

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


@pytest.mark.parametrize(
    "datos",
    [
        "http://169.254.169.254/latest/meta-data",
        "http://opendata.aemet.es/opendata/sh/tar",
        "https://atacante.example/opendata/sh/tar",
    ],
)
async def test_datos_url_fuera_de_aemet_no_se_sigue(datos: str) -> None:
    # datos_url viene del JSON del upstream: si apunta fuera de AEMET (o va
    # sin TLS), el segundo salto no debe ocurrir jamas (seria una SSRF).
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(str(request.url))
        return httpx.Response(200, text=_envelope(datos=datos))

    with pytest.raises(AemetProtocolError, match="outside opendata.aemet.es"):
        await _client(handler).fetch_warnings()

    assert requests == [LAST_BULLETIN_URL]


async def test_datos_gigante_es_transitorio(monkeypatch: pytest.MonkeyPatch) -> None:
    # C3 (ADR-0017): el tar del segundo salto se lee por streaming con tope.
    monkeypatch.setattr(settings, "HTTP_MAX_RESPONSE_BYTES", 16)

    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == LAST_BULLETIN_URL:
            return httpx.Response(200, text=_envelope())
        return httpx.Response(200, content=b"x" * 4096)

    with pytest.raises(AemetTransientError, match="too large"):
        await _client(handler).fetch_warnings()


async def test_miembro_de_tar_demasiado_grande_es_error_de_protocolo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # C4 (ADR-0017): un miembro declarado enorme es un archivo hostil; se
    # comprueba member.size ANTES de leer el contenido.
    monkeypatch.setattr(aemet_http, "_MAX_TAR_MEMBER_BYTES", 4)

    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == LAST_BULLETIN_URL:
            return httpx.Response(200, text=_envelope())
        return httpx.Response(200, content=_tar_with_caps(count=1))

    with pytest.raises(AemetProtocolError, match="too large"):
        await _client(handler).fetch_warnings()


async def test_tar_con_demasiados_miembros_es_error_de_protocolo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(aemet_http, "_MAX_TAR_MEMBERS", 1)

    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == LAST_BULLETIN_URL:
            return httpx.Response(200, text=_envelope())
        return httpx.Response(200, content=_tar_with_caps(count=3))

    with pytest.raises(AemetProtocolError, match="too many members"):
        await _client(handler).fetch_warnings()
