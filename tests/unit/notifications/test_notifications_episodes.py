from datetime import UTC, datetime, timedelta

import pytest

from app.notifications.event_handlers.match_notifications import match_notifications
from app.notifications.services.episodes import (
    Action,
    OpenEpisode,
    decide,
    episode_key,
    is_current,
)

T = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)
GRACE = timedelta(hours=3)


def _ep(notified: int, expires: datetime | None) -> OpenEpisode:
    return OpenEpisode(id=1, notified_severity=notified, expires_at=expires)


@pytest.mark.parametrize(
    ("episode", "severity", "expected"),
    [
        (None, 2, Action.OPEN),
        # AEMET vigente: mismo nivel silencio, sube escala, baja silencio.
        (_ep(2, T + timedelta(hours=5)), 2, Action.TOUCH),
        (_ep(2, T + timedelta(hours=5)), 3, Action.ESCALATE),
        (_ep(3, T + timedelta(hours=5)), 2, Action.TOUCH),
        # Caducado pero dentro de la gracia: el Update que cerro el anterior.
        (_ep(2, T - timedelta(hours=2)), 2, Action.TOUCH),
        # Frontera: expires + gracia == batch_at ya no es vigente.
        (_ep(2, T - GRACE), 2, Action.OPEN),
        (_ep(4, T - timedelta(days=1)), 2, Action.OPEN),
        # IGN/EFFIS: sin caducidad, vigente siempre.
        (_ep(2, None), 2, Action.TOUCH),
        (_ep(2, None), 4, Action.ESCALATE),
    ],
)
def test_decide(episode: OpenEpisode | None, severity: int, expected: Action) -> None:
    assert decide(episode, severity=severity, batch_at=T, grace=GRACE) is expected


def test_vigencia() -> None:
    assert not is_current(None, batch_at=T, grace=GRACE)
    assert is_current(_ep(2, None), batch_at=T, grace=GRACE)
    assert is_current(_ep(2, T - GRACE + timedelta(microseconds=1)), batch_at=T, grace=GRACE)


@pytest.mark.parametrize(
    ("source", "external_id", "attrs", "key"),
    [
        ("aemet", "cap-1", {"phenomenon": "TO;Tormentas"}, "aemet:TO"),
        ("aemet", "cap-2", {"phenomenon": "AT"}, "aemet:AT"),
        ("aemet", "cap-3", {"event": "Aviso de lluvias"}, "aemet:Aviso de lluvias"),
        ("aemet", "cap-4", {}, "aemet:desconocido"),
        ("ign", "es2026abc", {"phenomenon": "x"}, "ign:es2026abc"),
        ("effis", "ba-77", {}, "effis:ba-77"),
    ],
)
def test_clave_de_episodio(source: str, external_id: str, attrs: dict, key: str) -> None:
    assert episode_key(source=source, external_id=external_id, attrs=attrs) == key


async def test_handler_salta_lotes_sin_batch_at() -> None:
    # Eventos publicados antes de que existiera la marca: sin tocar la BD.
    await match_notifications({"source": "aemet", "inserted": 1, "updated": 0, "closed": 0})
