"""Parser del GeoRSS de sismologia del IGN (docs/sources.md).

El feed (RSS 2.0 + namespace geo) publica los ultimos 10 dias y esconde los
datos duros donde puede: el id estable (evid) va en el query string del guid,
lat/lon en geo:lat / geo:long, y la magnitud, la region y la fecha-hora van
EMBEBIDAS en el texto castellano de description.

La fecha llega sin marcador de zona; el spike de la fase 0 la identifico como
hora oficial peninsular, asi que aqui se interpreta como Europe/Madrid y se
convierte a UTC. La cadena original se conserva en attrs por si esa doctrina
resulta equivocada: el dato crudo sobrevive a la interpretacion.
"""

import logging
import math
import re
from datetime import UTC, datetime
from urllib.parse import parse_qs, urlparse
from xml.etree.ElementTree import Element
from zoneinfo import ZoneInfo

from defusedxml import ElementTree

from app.core.ign.exceptions import IgnProtocolError
from app.core.ign.types import IgnRecord

logger = logging.getLogger(__name__)

_GEO_NS = "{http://www.w3.org/2003/01/geo/wgs84_pos#}"
_TZ_MADRID = ZoneInfo("Europe/Madrid")

# "...terremoto de magnitud 3.5 en GOLFO DE CADIZ en la fecha 02/07/2026
# 7:06:37 en la siguiente localizacion: ...". La region se corta en el
# ultimo "en la fecha" porque puede contener "en" (p.ej. "E BENI BERBERE.MAC").
_DESCRIPTION_RE = re.compile(
    r"magnitud\s+(?P<magnitude>\d+(?:\.\d+)?)\s+en\s+(?P<region>.+?)\s+en la fecha\s+"
    r"(?P<moment>\d{2}/\d{2}/\d{4} \d{1,2}:\d{2}:\d{2})"
)


def parse_georss(payload: bytes) -> list[IgnRecord]:
    """Feed GeoRSS completo -> registros normalizados.

    Un item suelto malformado se salta con warning (el feed sigue siendo
    util); si NINGUN item se entiende, es un cambio de contrato y se lanza
    IgnProtocolError.
    """
    try:
        root = ElementTree.fromstring(payload)
    except Exception as exc:
        raise IgnProtocolError(f"unparseable GeoRSS feed: {exc}") from exc

    items = root.findall("./channel/item")
    records = []
    for item in items:
        record = _parse_item(item)
        if record is not None:
            records.append(record)
    if items and not records:
        raise IgnProtocolError(f"none of the {len(items)} feed items were parseable")
    if len(records) < len(items):
        logger.warning(
            "ign georss: %d of %d items skipped as malformed", len(items) - len(records), len(items)
        )
    return records


def _parse_item(item: Element) -> IgnRecord | None:
    guid = item.findtext("guid") or item.findtext("link") or ""
    evid = parse_qs(urlparse(guid).query).get("evid", [""])[0]
    lat_text = item.findtext(f"{_GEO_NS}lat")
    lon_text = item.findtext(f"{_GEO_NS}long")
    match = _DESCRIPTION_RE.search(item.findtext("description") or "")
    if not (evid and lat_text and lon_text and match):
        return None

    latitude = float(lat_text)
    longitude = float(lon_text)
    # float() acepta "nan", "inf" y "1e999"; una coordenada asi produciria
    # una geometria invalida, de modo que invalida el item (no el feed).
    if not (math.isfinite(latitude) and math.isfinite(longitude)):
        return None
    if not (-90.0 <= latitude <= 90.0 and -180.0 <= longitude <= 180.0):
        return None

    raw_moment = match.group("moment")
    occurred_local = datetime.strptime(raw_moment, "%d/%m/%Y %H:%M:%S").replace(tzinfo=_TZ_MADRID)
    return IgnRecord(
        external_id=evid,
        magnitude=float(match.group("magnitude")),
        region=match.group("region"),
        latitude=latitude,
        longitude=longitude,
        occurred_at=occurred_local.astimezone(UTC),
        attrs={"raw_local_moment": raw_moment},
    )


__all__ = ["parse_georss"]
