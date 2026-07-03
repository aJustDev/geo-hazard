from datetime import UTC, datetime

from app.core.aemet.types import MSG_TYPE_ALERT, AemetWarning


def _default_warnings() -> list[AemetWarning]:
    # Dos avisos sinteticos calcados del boletin real: uno naranja ingerible
    # y uno verde, que el use case debe dejar fuera (verde = sin riesgo).
    sent = datetime(2026, 7, 2, 16, 28, 3, tzinfo=UTC)
    return [
        AemetWarning(
            external_id="fake-aemet-naranja-1",
            msg_type=MSG_TYPE_ALERT,
            sent=sent,
            event="Aviso de temperaturas maximas de nivel naranja",
            phenomenon="AT;Temperaturas maximas",
            level="naranja",
            onset=datetime(2026, 7, 3, 11, 0, 0, tzinfo=UTC),
            expires=datetime(2026, 7, 3, 18, 59, 59, tzinfo=UTC),
            polygon="39.14,-5.58 39.19,-5.61 39.21,-5.56 39.14,-5.58",
            zone="700602",
            area_desc="La Siberia extremena",
            attrs={"probability": "40%-70%"},
        ),
        AemetWarning(
            external_id="fake-aemet-verde-1",
            msg_type=MSG_TYPE_ALERT,
            sent=sent,
            event="Aviso de costeros de nivel verde",
            phenomenon="CF;Fenomenos costeros",
            level="verde",
            onset=datetime(2026, 7, 3, 0, 0, 0, tzinfo=UTC),
            expires=datetime(2026, 7, 3, 21, 59, 59, tzinfo=UTC),
            polygon="43.4,-8.3 43.6,-8.1 43.5,-7.9 43.4,-8.3",
            zone="611304",
            area_desc="Costa - A Marina",
        ),
    ]


class AemetFakeClient:
    """Driver sin red para dev y tests. Cumple el Protocol AemetClient."""

    def __init__(self, *, warnings: list[AemetWarning] | None = None) -> None:
        self._warnings = warnings if warnings is not None else _default_warnings()

    async def fetch_warnings(self) -> list[AemetWarning]:
        return list(self._warnings)


__all__ = ["AemetFakeClient"]
