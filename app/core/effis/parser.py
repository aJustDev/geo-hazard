"""Parser del GeoJSON WFS de EFFIS (mapfile gwis, docs/sources.md).

Dos rarezas de la fuente que se normalizan AQUI y en ningun otro sitio,
siguiendo el principio de types.py (el resto del sistema no sabe como habla
EFFIS):

- El WFS 1.0.0 de gwis serializa las coordenadas INVERTIDAS [lat, lon]
  (verificado contra geografia conocida el 2026-07-04). El swap a GeoJSON
  canonico (lon, lat) ocurre solo en este modulo, igual que el de CAP ocurre
  solo en cap_polygon_to_wkb.
- Los timestamps llegan sin marcador de zona. Los productos satelitales de
  EFFIS publican en UTC, asi que se interpretan como UTC; la cadena cruda
  sobrevive en attrs por si la doctrina resultara equivocada (mismo criterio
  que la hora local del feed IGN).
"""

import json
import logging
from datetime import UTC, datetime
from typing import Any

from app.core.effis.exceptions import EffisProtocolError
from app.core.effis.types import KIND_BURNT_AREA, KIND_HOTSPOT, EffisRecord

logger = logging.getLogger(__name__)

_HOTSPOT_GEOMETRIES = ("Point",)
_BURNT_AREA_GEOMETRIES = ("Polygon", "MultiPolygon")


def parse_hotspots(payload: bytes) -> list[EffisRecord]:
    """GeoJSON de una capa *.hs.* -> registros hotspot normalizados."""
    return _parse(payload, kind=KIND_HOTSPOT)


def parse_burnt_areas(payload: bytes) -> list[EffisRecord]:
    """GeoJSON de una capa nrt.ba.poly.* -> registros burnt_area normalizados."""
    return _parse(payload, kind=KIND_BURNT_AREA)


def _parse(payload: bytes, *, kind: str) -> list[EffisRecord]:
    """Un feature suelto malformado se salta con warning (el lote sigue siendo
    util); si NINGUNO se entiende, es un cambio de contrato y se lanza
    EffisProtocolError. Mismo criterio que el parser de IGN.
    """
    try:
        document = json.loads(payload)
        features = document["features"]
    except (ValueError, TypeError, KeyError) as exc:
        raise EffisProtocolError(f"unparseable EFFIS WFS response: {exc}") from exc

    records = []
    for feature in features:
        record = _parse_feature(feature, kind=kind)
        if record is not None:
            records.append(record)
    if features and not records:
        raise EffisProtocolError(f"none of the {len(features)} EFFIS features were parseable")
    if len(records) < len(features):
        logger.warning(
            "effis wfs: %d of %d features skipped as malformed",
            len(features) - len(records),
            len(features),
        )
    return records


def _parse_feature(feature: dict[str, Any], *, kind: str) -> EffisRecord | None:
    try:
        properties = feature["properties"]
        geometry = feature["geometry"]
        if kind == KIND_HOTSPOT:
            if geometry["type"] not in _HOTSPOT_GEOMETRIES:
                return None
            return EffisRecord(
                external_id=f"hs-{properties['id']}",
                kind=kind,
                geometry=_swap_axes(geometry),
                observed_at=_parse_moment(properties["acq_at"]),
                attrs={
                    "product": "all.hs",
                    "class": properties.get("CLASS", ""),
                    "raw_acquired_at": properties["acq_at"],
                },
            )
        if geometry["type"] not in _BURNT_AREA_GEOMETRIES:
            return None
        return EffisRecord(
            external_id=f"ba-{properties['fire_id']}",
            kind=kind,
            geometry=_swap_axes(geometry),
            observed_at=_parse_moment(properties["initialdate"]),
            area_ha=float(properties["area"]),
            attrs={
                "product": "nrt.ba",
                "fire_id": str(properties["fire_id"]),
                "raw_initialdate": properties["initialdate"],
                "raw_finaldate": properties.get("finaldate", ""),
            },
        )
    except KeyError, TypeError, ValueError:
        return None


def _parse_moment(raw: str) -> datetime:
    return datetime.strptime(raw, "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)


def _swap_axes(geometry: dict[str, Any]) -> dict[str, Any]:
    return {"type": geometry["type"], "coordinates": _swap_pairs(geometry["coordinates"])}


def _swap_pairs(coords: Any) -> Any:
    # Par hoja [lat, lon] -> [lon, lat]; recursivo para anillos y multipartes.
    if isinstance(coords[0], int | float):
        return [coords[1], coords[0]]
    return [_swap_pairs(part) for part in coords]


__all__ = ["parse_burnt_areas", "parse_hotspots"]
