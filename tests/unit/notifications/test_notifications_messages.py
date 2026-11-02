import json
import uuid
from datetime import UTC, datetime
from typing import Any

from app.notifications.schemas.delivery import ClaimedSubscription, PendingDelivery
from app.notifications.services.messages import (
    describe,
    relevant_degraded,
    render_ntfy,
    render_webhook,
)
from app.notifications.services.texts import NOTICE, phenomenon_name, when, zone_for

BASE = "https://geohazard.ajustino.dev"
EVENT_ID = "6f1c0d4e-0000-4000-8000-000000000001"


def _feature(hazard: str, attrs: dict[str, Any], *, lon: float = -1.1, **props: Any) -> dict:
    source = {"weather_warning": "aemet", "earthquake": "ign", "wildfire": "effis"}[hazard]
    return {
        "type": "Feature",
        "id": EVENT_ID,
        "geometry": {"type": "Point", "coordinates": [lon, 37.9]},
        "properties": {
            "source": source,
            "hazard_type": hazard,
            "severity": 2,
            "starts_at": "2026-11-04T13:00:00+00:00",
            "ends_at": "2026-11-04T20:59:59+00:00",
            "external_id": "x",
            "attrs": attrs,
            **props,
        },
    }


def _warning(zone: str, level: str = "naranja", **kw: Any) -> dict:
    return _feature(
        "weather_warning", {"level": level, "phenomenon": "TO;Tormentas", "area_desc": zone}, **kw
    )


def _delivery(items: list[dict], *, severity: int = 3, reason: str = "opened", count=None):
    return PendingDelivery(
        id=uuid.uuid4(),
        episode_id=uuid.uuid4(),
        reason=reason,
        severity=severity,
        items=items,
        item_count=len(items) if count is None else count,
    )


def _subscription(deliveries: list[PendingDelivery], types=None) -> ClaimedSubscription:
    return ClaimedSubscription(
        id=uuid.uuid4(),
        channel="ntfy",
        endpoint="https://ntfy.sh",
        credential="geohazard-x",
        hazard_types=types or ["weather_warning", "earthquake", "wildfire"],
        area_id=uuid.uuid4(),
        area_label="Murcia",
        previous_retry_at=None,
        deliveries=deliveries,
    )


def test_hora_en_la_zona_del_evento() -> None:
    raw = "2026-11-04T13:00:00+00:00"  # miercoles
    assert when(raw, zone_for(_warning("a"))) == "mie 4 nov 14:00"
    assert when(raw, zone_for(_warning("a", lon=-15.6))) == "mie 4 nov 13:00"
    assert when(None, zone_for(_warning("a"))) == "?"


def test_nombre_de_fenomeno() -> None:
    assert phenomenon_name("TO;Tormentas") == "tormentas"
    assert phenomenon_name("Lluvias") == "lluvias"
    assert phenomenon_name(None) == "fenomeno desconocido"


def test_aviso_con_zonas_y_ventana() -> None:
    zones = ["Vega del Segura", "Altiplano", "Noroeste", "Campo de Cartagena", "Lorca"]
    headline, line = describe(_delivery([_warning(z) for z in zones]))
    assert headline == "Aviso naranja por tormentas"
    assert line == (
        "Aviso naranja por tormentas: Vega del Segura, Altiplano, Noroeste y 2 mas, "
        "de mie 4 nov 14:00 a mie 4 nov 21:59."
    )


def test_aviso_cuenta_las_zonas_que_no_caben_en_items() -> None:
    _, line = describe(_delivery([_warning("Vega del Segura")], count=30))
    assert "Vega del Segura y 29 mas" in line


def test_aviso_que_sube_de_nivel() -> None:
    headline, _ = describe(_delivery([_warning("Vega", level="rojo")], reason="escalated"))
    assert headline == "Sube a rojo el aviso por tormentas"


def test_terremoto() -> None:
    quake = _feature("earthquake", {"magnitude": 4.2, "region": "SE CARTAGENA.MU"})
    assert describe(_delivery([quake]))[1] == (
        "Terremoto de magnitud 4.2 en SE CARTAGENA.MU, mie 4 nov 14:00."
    )
    assert describe(_delivery([quake], reason="escalated"))[0] == (
        "Revisado al alza: terremoto de magnitud 4.2"
    )
    assert describe(_delivery([_feature("earthquake", {})]))[0] == "Terremoto de magnitud ?"


def test_incendio() -> None:
    fire = _feature("wildfire", {"kind": "burnt_area", "area_ha": 612.4})
    assert describe(_delivery([fire]))[1] == "Incendio de 612 ha, detectado mie 4 nov 14:00."
    assert describe(_delivery([fire], reason="escalated"))[0] == "Crece el incendio: 612 ha"
    assert describe(_delivery([_feature("wildfire", {})]))[0] == (
        "Incendio de extension desconocida"
    )


def test_ntfy_de_una_entrega_lleva_titulo_enlace_y_prioridad() -> None:
    message = render_ntfy(
        _subscription([_delivery([_warning("Vega del Segura")], severity=3)]),
        [],
        base_url=BASE + "/",
        max_items=5,
    )
    assert message.title == "Aviso naranja por tormentas - Murcia"
    assert message.priority == 4
    assert message.tags == ("warning",)
    assert message.click == f"{BASE}/v1/events/{EVENT_ID}"
    assert NOTICE in message.body
    assert "Fuente: AEMET" in message.body
    assert "IGN" not in message.body  # solo la atribucion de lo que aparece


def test_ntfy_de_varias_entregas_agrupa_y_corta() -> None:
    quake = _feature("earthquake", {"magnitude": 3.1, "region": "MURCIA"})
    deliveries = [_delivery([_warning(f"z{i}")], severity=4 if i == 0 else 2) for i in range(6)]
    message = render_ntfy(
        _subscription([*deliveries, _delivery([quake], severity=2)]),
        [],
        base_url=BASE,
        max_items=5,
    )
    assert message.title == "7 avisos en Murcia"
    assert message.priority == 5
    assert message.tags == ("globe_with_meridians", "warning")
    assert message.click is None
    assert "Y 2 mas avisos." in message.body
    assert message.body.count("Aviso ") == 5


def test_solo_avisa_de_fuentes_degradadas_de_las_que_depende() -> None:
    subscription = _subscription([_delivery([_warning("Vega")])], types=["weather_warning"])
    assert relevant_degraded(subscription.hazard_types, ["effis", "aemet"]) == ["aemet"]

    body = render_ntfy(subscription, ["effis", "aemet"], base_url=BASE, max_items=5).body
    assert "sin datos recientes de AEMET;" in body
    assert "EFFIS" not in body
    assert "sin datos" not in render_ntfy(subscription, ["effis"], base_url=BASE, max_items=5).body


def test_sobre_webhook_v1() -> None:
    delivery = _delivery([_warning("Vega")], count=3)
    subscription = _subscription([delivery], types=["weather_warning"])
    message_id = uuid.uuid4()
    sent_at = datetime(2026, 11, 4, 13, 5, tzinfo=UTC)

    envelope = json.loads(
        render_webhook(subscription, ["aemet", "ign"], message_id=message_id, sent_at=sent_at)
    )

    assert envelope["version"] == 1
    assert envelope["message_id"] == str(message_id)
    assert envelope["subscription_id"] == str(subscription.id)
    assert envelope["area"] == {"id": str(subscription.area_id), "label": "Murcia"}
    assert envelope["notice"] == NOTICE
    assert envelope["degraded_sources"] == ["aemet"]
    assert [a["source"] for a in envelope["attribution"]] == ["aemet"]
    (item,) = envelope["items"]
    assert item["delivery_id"] == str(delivery.id)
    assert item["episode_id"] == str(delivery.episode_id)
    assert item["reason"] == "opened"
    assert item["event_count"] == 3
    assert item["features"][0]["properties"]["attrs"]["area_desc"] == "Vega"
