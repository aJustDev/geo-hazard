"""Textos en castellano de los avisos (ADR-0021). Servicio puro.

Todo lo que lee una persona sale de aqui, listo para i18n cuando llegue el
frontend. Las horas van en la zona del evento: Europe/Madrid, o
Atlantic/Canary al oeste de 13 W. Los nombres de dias y meses estan
escritos a mano porque la imagen no trae el locale es_ES.
"""

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

NOTICE = (
    "No es un aviso oficial. Consulta AEMET y, ante una emergencia, llama al 112 "
    "(los avisos oficiales llegan por ES-Alert)."
)

SOURCE_NAMES = {"aemet": "AEMET", "ign": "IGN", "effis": "EFFIS"}

_PENINSULA = ZoneInfo("Europe/Madrid")
_CANARIAS = ZoneInfo("Atlantic/Canary")
_CANARIAS_MAX_LON = -13.0
_WEEKDAYS = ("lun", "mar", "mie", "jue", "vie", "sab", "dom")
_MONTHS = ("ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic")


def _first_lon(coordinates: Any) -> float | None:
    if isinstance(coordinates, list | tuple) and coordinates:
        if isinstance(coordinates[0], int | float):
            return float(coordinates[0])
        return _first_lon(coordinates[0])
    return None


def zone_for(feature: dict[str, Any]) -> ZoneInfo:
    lon = _first_lon((feature.get("geometry") or {}).get("coordinates"))
    return _CANARIAS if lon is not None and lon < _CANARIAS_MAX_LON else _PENINSULA


def when(raw: str | None, zone: ZoneInfo) -> str:
    """'2026-11-04T13:00:00+00:00' -> 'mie 4 nov 14:00' en la zona dada."""
    if not raw:
        return "?"
    moment = datetime.fromisoformat(raw).astimezone(zone)
    return f"{_WEEKDAYS[moment.weekday()]} {moment.day} {_MONTHS[moment.month - 1]} {moment:%H:%M}"


def phenomenon_name(raw: str | None) -> str:
    """'TO;Tormentas' -> 'tormentas'."""
    if not raw:
        return "fenomeno desconocido"
    return raw.split(";", 1)[-1].strip().lower() or raw


def degraded_note(sources: list[str]) -> str:
    names = ", ".join(SOURCE_NAMES.get(s, s) for s in sources)
    return f"Ojo: sin datos recientes de {names}; puede haber avisos que no han llegado."


def and_more(count: int) -> str:
    return f"y {count} mas"


__all__ = [
    "NOTICE",
    "SOURCE_NAMES",
    "and_more",
    "degraded_note",
    "phenomenon_name",
    "when",
    "zone_for",
]
