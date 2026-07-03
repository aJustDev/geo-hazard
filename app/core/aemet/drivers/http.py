"""Adaptador HTTP real de los avisos CAP de AEMET OpenData.

Flujo de dos saltos (docs/sources.md): la API devuelve un sobre JSON con una
URL temporal en `datos`; esa URL sirve un tar con un CAP XML por aviso y
zona. La API key viaja SOLO en la cabecera `api_key` del primer salto; la
URL temporal no la incorpora, asi que nunca acaba en logs de terceros.
"""

import io
import logging
import tarfile

import httpx

from app.core.aemet.exceptions import AemetProtocolError, AemetTransientError
from app.core.aemet.parser import parse_cap
from app.core.aemet.types import AemetWarning

logger = logging.getLogger(__name__)

LAST_BULLETIN_URL = "https://opendata.aemet.es/opendata/api/avisos_cap/ultimoelaborado/area/esp"
_TIMEOUT_SECONDS = 60.0


class AemetHttpClient:
    """Cumple el Protocol AemetClient contra AEMET OpenData.

    `transport` es inyectable para tests (httpx.MockTransport): mismo codigo
    de red, saltos y mapeo de errores, sin tocar la red.
    """

    def __init__(self, *, api_key: str, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._api_key = api_key
        self._transport = transport

    async def fetch_warnings(self) -> list[AemetWarning]:
        try:
            async with httpx.AsyncClient(
                timeout=_TIMEOUT_SECONDS, transport=self._transport
            ) as client:
                archive = await self._fetch_archive(client)
        except httpx.HTTPError as exc:
            raise AemetTransientError(f"AEMET OpenData unreachable: {exc}") from exc
        return self._parse_archive(archive)

    async def _fetch_archive(self, client: httpx.AsyncClient) -> bytes:
        envelope_response = await client.get(LAST_BULLETIN_URL, headers={"api_key": self._api_key})
        if envelope_response.status_code >= 500:
            raise AemetTransientError(f"AEMET API returned {envelope_response.status_code}")
        try:
            envelope = envelope_response.json()
        except ValueError as exc:
            raise AemetProtocolError("AEMET envelope is not JSON") from exc

        # AEMET codifica el estado DENTRO del sobre ademas del status HTTP:
        # 429 = cuota agotada (reintentable), 401/403 = key rechazada.
        estado = envelope.get("estado")
        datos_url = envelope.get("datos")
        if estado == 429:
            raise AemetTransientError("AEMET API quota exhausted")
        if estado != 200 or not datos_url:
            raise AemetProtocolError(
                f"AEMET envelope estado={estado!r}: {envelope.get('descripcion', 'sin descripcion')!r}"
            )

        data_response = await client.get(datos_url)
        if data_response.status_code != 200:
            # La URL de datos es temporal: si caduco, el siguiente poll pide
            # una fresca. Cualquier fallo aqui es reintentable.
            raise AemetTransientError(f"AEMET datos URL returned {data_response.status_code}")
        return data_response.content

    @staticmethod
    def _parse_archive(data: bytes) -> list[AemetWarning]:
        # Solo lectura en memoria via extractfile: nunca se extrae a disco,
        # asi que las trampas clasicas de tar (rutas ../) no aplican.
        warnings: list[AemetWarning] = []
        skipped = 0
        try:
            with tarfile.open(fileobj=io.BytesIO(data), mode="r:*") as archive:
                for member in archive:
                    if not member.isfile():
                        continue
                    file = archive.extractfile(member)
                    if file is None:
                        continue
                    try:
                        warnings.append(parse_cap(file.read()))
                    except AemetProtocolError:
                        skipped += 1
        except tarfile.TarError as exc:
            raise AemetProtocolError(f"AEMET datos URL did not return a tar: {exc}") from exc
        if skipped and not warnings:
            raise AemetProtocolError("every CAP file in the AEMET tar failed to parse")
        if skipped:
            logger.warning("aemet tar: %d CAP files skipped as malformed", skipped)
        return warnings


__all__ = ["LAST_BULLETIN_URL", "AemetHttpClient"]
