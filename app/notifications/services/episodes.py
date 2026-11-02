"""Regla de episodios (ADR-0021). Servicio puro.

Un aviso solo sale cuando un episodio se abre o sube de severidad; todo lo
demas (un Update de AEMET al mismo nivel, una bajada, un re-servido, una
revision igual) es silencio.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any


class Action(StrEnum):
    OPEN = "open"  # no hay episodio vigente: se abre (y se cierra el caducado)
    ESCALATE = "escalate"  # vigente y la severidad sube: se avisa otra vez
    TOUCH = "touch"  # vigente sin subir: se actualiza en silencio


@dataclass(frozen=True, slots=True)
class OpenEpisode:
    id: Any
    notified_severity: int
    # Solo AEMET: max ends_at ingerido. None = vigente siempre (IGN, EFFIS).
    expires_at: datetime | None


def episode_key(*, source: str, external_id: str, attrs: dict[str, Any]) -> str:
    """AEMET agrupa por fenomeno (el codigo antes de ';'): cada Update trae
    un identificador nuevo. IGN y EFFIS, por evento (ids estables)."""
    if source == "aemet":
        raw = attrs.get("phenomenon") or attrs.get("event") or "desconocido"
        return f"aemet:{str(raw).split(';', 1)[0].strip()}"
    return f"{source}:{external_id}"


def is_current(episode: OpenEpisode | None, *, batch_at: datetime, grace: timedelta) -> bool:
    """La gracia cubre el hueco que deja un Update al cerrar el aviso que
    sustituye en el mismo lote que trae el nuevo."""
    if episode is None:
        return False
    return episode.expires_at is None or episode.expires_at + grace > batch_at


def decide(
    episode: OpenEpisode | None, *, severity: int, batch_at: datetime, grace: timedelta
) -> Action:
    if episode is None or not is_current(episode, batch_at=batch_at, grace=grace):
        return Action.OPEN
    if severity > episode.notified_severity:
        return Action.ESCALATE
    return Action.TOUCH


__all__ = ["Action", "OpenEpisode", "decide", "episode_key", "is_current"]
