"""Adaptador HTTP real del WFS de EFFIS (mapfile gwis, docs/sources.md).

El mapfile /effis del mismo servidor tiene las capas NRT rotas server-side;
gwis es el que alimenta el visor oficial y responde (ADR-0015). Las ventanas
temporales las resuelve el NOMBRE de capa (.week), no el parametro TIME, que
el WFS ignora en silencio.

El servidor colgaba sin User-Agent de navegador en el spike de la fase 2;
gwis respondio sin UA el 2026-07-04, pero se envia uno identificable por
cortesia operacional (como IGN) y HTTP/1.1 (httpx no negocia h2 salvo
peticion explicita; el spike registro cuelgues con h2).
"""

import httpx

from app.core.effis.exceptions import EffisProtocolError, EffisTransientError
from app.core.effis.parser import parse_burnt_areas, parse_hotspots
from app.core.effis.types import EffisRecord

BASE_URL = "https://maps.effis.emergency.copernicus.eu/gwis"
HOTSPOTS_LAYER = "all.hs.week"
BURNT_AREAS_LAYER = "nrt.ba.poly.week"

# Rectangulo peninsula + Baleares + Canarias. Un bbox es un rectangulo:
# incluye territorio vecino (Portugal, norte de Africa), igual que el feed
# IGN publica sismos fronterizos. Se ingiere tal cual (ADR-0015).
_BBOX_SPAIN = "-19,27,5,44"
_TIMEOUT_SECONDS = 60.0
_USER_AGENT = "geo-hazard/0.1 (+https://github.com/aJustDev/geo-hazard)"


class EffisHttpClient:
    """Cumple el Protocol EffisClient contra el WFS real.

    `transport` es inyectable para tests (httpx.MockTransport): mismo codigo
    de red y de mapeo de errores, sin tocar la red.
    """

    def __init__(self, *, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._transport = transport

    async def fetch_hotspots(self) -> list[EffisRecord]:
        return parse_hotspots(await self._get_features(HOTSPOTS_LAYER))

    async def fetch_burnt_areas(self) -> list[EffisRecord]:
        return parse_burnt_areas(await self._get_features(BURNT_AREAS_LAYER))

    async def _get_features(self, typename: str) -> bytes:
        params = {
            "service": "WFS",
            "version": "1.0.0",
            "request": "GetFeature",
            "typename": typename,
            "outputFormat": "geojson",
            "bbox": _BBOX_SPAIN,
        }
        try:
            async with httpx.AsyncClient(
                timeout=_TIMEOUT_SECONDS,
                transport=self._transport,
                headers={"User-Agent": _USER_AGENT},
            ) as client:
                response = await client.get(BASE_URL, params=params)
        except httpx.HTTPError as exc:
            raise EffisTransientError(f"EFFIS WFS unreachable: {exc}") from exc

        if response.status_code >= 500:
            raise EffisTransientError(f"EFFIS WFS returned {response.status_code}")
        if response.status_code != 200:
            # Un 4xx no se arregla reintentando: la URL o el contrato cambiaron.
            raise EffisProtocolError(f"EFFIS WFS returned {response.status_code}")
        if b"ServiceExceptionReport" in response.content[:512]:
            # MapServer responde 200 con una excepcion XML cuando el backend
            # de la capa falla (observado durante dias en /effis): es un
            # fallo del servidor, no un cambio de contrato. Reintentable.
            raise EffisTransientError(f"EFFIS WFS layer backend error on {typename}")
        return response.content


__all__ = ["BASE_URL", "BURNT_AREAS_LAYER", "HOTSPOTS_LAYER", "EffisHttpClient"]
