"""Adaptador HTTP real del GeoRSS de sismologia del IGN.

Endpoint publico y sin autenticacion (docs/sources.md). A diferencia de
EFFIS, el servidor del IGN no exige User-Agent de navegador; se envia uno
identificable por cortesia operacional.
"""

import httpx

from app.core.ign.exceptions import IgnProtocolError, IgnTransientError
from app.core.ign.parser import parse_georss
from app.core.ign.types import IgnRecord

FEED_URL = "https://www.ign.es/ign/RssTools/sismologia.xml"
_TIMEOUT_SECONDS = 30.0
_USER_AGENT = "geo-hazard/0.1 (+https://github.com/aJustDev/geo-hazard)"


class IgnHttpClient:
    """Cumple el Protocol IgnClient contra el feed real.

    `transport` es inyectable para tests (httpx.MockTransport): mismo codigo
    de red y de mapeo de errores, sin tocar la red.
    """

    def __init__(self, *, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._transport = transport

    async def fetch_earthquakes(self) -> list[IgnRecord]:
        try:
            async with httpx.AsyncClient(
                timeout=_TIMEOUT_SECONDS,
                transport=self._transport,
                headers={"User-Agent": _USER_AGENT},
            ) as client:
                response = await client.get(FEED_URL)
        except httpx.HTTPError as exc:
            raise IgnTransientError(f"IGN feed unreachable: {exc}") from exc

        if response.status_code >= 500:
            raise IgnTransientError(f"IGN feed returned {response.status_code}")
        if response.status_code != 200:
            # Un 4xx no se arregla reintentando: la URL o el contrato cambiaron.
            raise IgnProtocolError(f"IGN feed returned {response.status_code}")
        return parse_georss(response.content)


__all__ = ["FEED_URL", "IgnHttpClient"]
