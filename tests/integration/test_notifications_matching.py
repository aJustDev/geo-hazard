"""Cruce de lotes con suscripciones (ADR-0021) contra PostGIS real.

Las filas se insertan a mano con created_at/updated_at explicitos: cada
lote es una marca de tiempo elegida, sin depender del reloj."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from geoalchemy2 import WKTElement
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.hazards.models import HazardEventORM, ProvinceORM
from app.notifications.models import (
    NotificationDeliveryORM,
    NotificationEpisodeORM,
    SubscriptionORM,
)
from app.notifications.repos.watch_area import WatchAreaRepo
from app.notifications.services.areas import bbox_area, circle_area, province_area
from app.notifications.use_cases.match_batch import MatchBatchUseCase

pytestmark = [pytest.mark.integration, pytest.mark.asyncio(loop_scope="session")]

T1 = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)
# Vega del Segura, dentro de Murcia.
VEGA = "POLYGON((-1.3 38.0, -1.0 38.0, -1.0 38.2, -1.3 38.2, -1.3 38.0))"
# Toca Murcia pero solapa sobre todo con Almeria (Valle del Almanzora).
ALMANZORA = "POLYGON((-2.3 37.45, -1.85 37.45, -1.85 37.65, -2.3 37.65, -2.3 37.45))"


async def _subscribe(
    factory: async_sessionmaker,
    area: str,
    *,
    types: list[str],
    severity_min: int = 2,
    status: str = "active",
) -> uuid.UUID:
    kind, _, raw = area.partition(":")
    async with factory() as session:
        repo = WatchAreaRepo(session)
        if kind == "province":
            watch_area = await repo.create_province(province_area(raw))
        elif kind == "circle":
            watch_area = await repo.create_circle(circle_area(raw))
        else:
            watch_area = await repo.create_bbox(bbox_area(raw))
        subscription = SubscriptionORM(
            watch_area_id=watch_area.id,
            hazard_types=types,
            severity_min=severity_min,
            channel="ntfy",
            endpoint="https://ntfy.sh",
            credential="geohazard-topic",
            status=status,
        )
        session.add(subscription)
        await session.commit()
        return subscription.id


async def _insert(factory: async_sessionmaker, *, at: datetime, wkt: str, **fields: Any) -> None:
    async with factory() as session:
        session.add(
            HazardEventORM(
                geom=WKTElement(wkt, srid=4326),
                content_hash=uuid.uuid4().hex,
                created_at=at,
                **fields,
            )
        )
        await session.commit()


async def _update(factory: async_sessionmaker, external_id: str, *, at: datetime, **values) -> None:
    async with factory() as session:
        await session.execute(
            update(HazardEventORM)
            .where(HazardEventORM.external_id == external_id)
            .values(updated_at=at, **values)
        )
        await session.commit()


async def _match(factory: async_sessionmaker, source: str, batch_at: datetime) -> int:
    async with factory() as session:
        created = await MatchBatchUseCase(session).execute(source=source, batch_at=batch_at)
        await session.commit()
        return created


async def _deliveries(
    factory: async_sessionmaker, subscription_id: uuid.UUID
) -> list[tuple[str, int, int]]:
    async with factory() as session:
        rows = await session.execute(
            select(
                NotificationDeliveryORM.reason,
                NotificationDeliveryORM.severity,
                NotificationDeliveryORM.item_count,
            )
            .where(NotificationDeliveryORM.subscription_id == subscription_id)
            .order_by(NotificationDeliveryORM.created_at, NotificationDeliveryORM.severity)
        )
        return [(reason, severity, count) for reason, severity, count in rows]


def _warning(external_id: str, level: str, ends_at: datetime, **kw: Any) -> dict[str, Any]:
    severity = {"amarillo": 2, "naranja": 3, "rojo": 4}[level]
    attrs = {
        "level": level,
        "phenomenon": kw.pop("phenomenon", "TO;Tormentas"),
        "area_desc": "Vega",
    }
    return dict(
        source="aemet",
        hazard_type="weather_warning",
        external_id=external_id,
        severity=severity,
        starts_at=kw.pop("starts_at", ends_at - timedelta(hours=8)),
        ends_at=ends_at,
        attrs=attrs,
        **kw,
    )


async def test_aemet_un_episodio_por_fenomeno(committing_factory: async_sessionmaker) -> None:
    sub = await _subscribe(committing_factory, "province:30", types=["weather_warning"])
    expires = T1 + timedelta(hours=30)

    # T1: aviso amarillo de manana (onset futuro): abre episodio.
    await _insert(committing_factory, at=T1, wkt=VEGA, **_warning("w1", "amarillo", expires))
    assert await _match(committing_factory, "aemet", T1) == 1

    # T2: un Update lo sustituye con otro id y cierra w1 en el mismo lote.
    t2 = T1 + timedelta(minutes=30)
    await _insert(committing_factory, at=t2, wkt=VEGA, **_warning("w2", "amarillo", expires))
    await _update(committing_factory, "w1", at=t2, ends_at=t2 - timedelta(minutes=5))
    assert await _match(committing_factory, "aemet", t2) == 0

    # T3: sube a naranja: escala. T4: baja a amarillo: silencio.
    t3 = t2 + timedelta(minutes=30)
    await _insert(committing_factory, at=t3, wkt=VEGA, **_warning("w3", "naranja", expires))
    assert await _match(committing_factory, "aemet", t3) == 1
    t4 = t3 + timedelta(minutes=30)
    await _insert(committing_factory, at=t4, wkt=VEGA, **_warning("w4", "amarillo", expires))
    assert await _match(committing_factory, "aemet", t4) == 0

    # Otro fenomeno en la misma zona es otro episodio.
    await _insert(
        committing_factory,
        at=t4 + timedelta(minutes=1),
        wkt=VEGA,
        **_warning("w-viento", "amarillo", expires, phenomenon="VI;Vientos"),
    )
    assert await _match(committing_factory, "aemet", t4 + timedelta(minutes=1)) == 1

    # T5: pasada la caducidad mas la gracia, el mismo fenomeno reabre.
    t5 = expires + timedelta(hours=3, minutes=1)
    await _insert(
        committing_factory,
        at=t5,
        wkt=VEGA,
        **_warning("w5", "amarillo", t5 + timedelta(hours=6)),
    )
    assert await _match(committing_factory, "aemet", t5) == 1

    # T6: un lote que solo cierra (retirado del boletin) no avisa.
    t6 = t5 + timedelta(minutes=30)
    await _update(committing_factory, "w5", at=t6, ends_at=t6)
    assert await _match(committing_factory, "aemet", t6) == 0

    assert await _deliveries(committing_factory, sub) == [
        ("opened", 2, 1),
        ("escalated", 3, 1),
        ("opened", 2, 1),
        ("opened", 2, 1),
    ]
    async with committing_factory() as session:
        episodes = (
            await session.execute(
                select(NotificationEpisodeORM.key, NotificationEpisodeORM.closed_at).order_by(
                    NotificationEpisodeORM.opened_at
                )
            )
        ).all()
    assert [(key, closed is not None) for key, closed in episodes] == [
        ("aemet:TO", True),
        ("aemet:VI", False),
        ("aemet:TO", False),
    ]


async def test_aemet_zona_vecina_no_avisa_a_la_provincia(
    committing_factory: async_sessionmaker,
) -> None:
    province = await _subscribe(committing_factory, "province:30", types=["weather_warning"])
    circle = await _subscribe(
        committing_factory, "circle:-2.05,37.55,30", types=["weather_warning"]
    )
    async with committing_factory() as session:
        touches = await session.scalar(
            select(
                func.ST_Intersects(ProvinceORM.geom, func.ST_GeomFromText(ALMANZORA, 4326))
            ).where(ProvinceORM.code == "30")
        )
    assert touches  # el poligono toca Murcia: la regla del mayor solape es la que decide

    expires = T1 + timedelta(hours=10)
    await _insert(
        committing_factory, at=T1, wkt=ALMANZORA, **_warning("w-alm", "amarillo", expires)
    )

    assert await _match(committing_factory, "aemet", T1) == 1
    assert await _deliveries(committing_factory, province) == []
    assert await _deliveries(committing_factory, circle) == [("opened", 2, 1)]


def _quake(external_id: str, magnitude: float, severity: int, starts_at: datetime) -> dict:
    return dict(
        source="ign",
        hazard_type="earthquake",
        external_id=external_id,
        severity=severity,
        starts_at=starts_at,
        ends_at=starts_at,
        attrs={"magnitude": magnitude, "region": "CARTAGENA.MU"},
    )


async def test_ign_por_sismo_con_revisiones(committing_factory: async_sessionmaker) -> None:
    sub = await _subscribe(committing_factory, "circle:-0.99,37.62,30", types=["earthquake"])
    quake_at = T1 - timedelta(hours=1)

    await _insert(
        committing_factory, at=T1, wkt="POINT(-0.95 37.6)", **_quake("q1", 3.1, 2, quake_at)
    )
    assert await _match(committing_factory, "ign", T1) == 1

    # Revision a la misma severidad: silencio. Al alza: escala.
    t2 = T1 + timedelta(minutes=15)
    await _update(committing_factory, "q1", at=t2, attrs={"magnitude": 3.3, "region": "X"})
    assert await _match(committing_factory, "ign", t2) == 0
    t3 = t2 + timedelta(minutes=15)
    await _update(committing_factory, "q1", at=t3, severity=3)
    assert await _match(committing_factory, "ign", t3) == 1

    # Un sismo de hace tres dias que entra ahora (ventana de 10 dias) no avisa,
    # ni uno fuera del circulo.
    t4 = t3 + timedelta(minutes=15)
    await _insert(
        committing_factory,
        at=t4,
        wkt="POINT(-0.95 37.6)",
        **_quake("q-viejo", 3.5, 2, t4 - timedelta(days=3)),
    )
    await _insert(
        committing_factory, at=t4, wkt="POINT(-3.7 40.4)", **_quake("q-madrid", 3.5, 2, t4)
    )
    assert await _match(committing_factory, "ign", t4) == 0

    assert await _deliveries(committing_factory, sub) == [("opened", 2, 1), ("escalated", 3, 1)]


async def test_ign_epicentro_en_el_borde_de_la_provincia(
    committing_factory: async_sessionmaker,
) -> None:
    sub = await _subscribe(committing_factory, "province:30", types=["earthquake"])
    # Murcia, a menos de 1 km del limite con Alicante.
    await _insert(
        committing_factory,
        at=T1,
        wkt="POINT(-0.977277 38.249481)",
        **_quake("q-borde", 3.0, 2, T1),
    )
    assert await _match(committing_factory, "ign", T1) == 1
    assert await _deliveries(committing_factory, sub) == [("opened", 2, 1)]


def _fire(external_id: str, severity: int, *, kind: str = "burnt_area", **kw: Any) -> dict:
    starts = T1 - timedelta(days=1)
    return dict(
        source="effis",
        hazard_type="wildfire",
        external_id=external_id,
        severity=severity,
        starts_at=starts,
        ends_at=kw.pop("ends_at", starts if kind == "hotspot" else None),
        attrs={"kind": kind, "area_ha": 600.0},
        **kw,
    )


async def test_effis_areas_quemadas_sin_hotspots(committing_factory: async_sessionmaker) -> None:
    sub = await _subscribe(committing_factory, "bbox:-1.7,37.9,-1.4,38.2", types=["wildfire"])
    fire_wkt = "POLYGON((-1.6 38.0, -1.5 38.0, -1.5 38.1, -1.6 38.1, -1.6 38.0))"

    await _insert(
        committing_factory, at=T1, wkt="POINT(-1.55 38.05)", **_fire("hs-1", 2, kind="hotspot")
    )
    await _insert(committing_factory, at=T1, wkt=fire_wkt, **_fire("ba-1", 3))
    assert await _match(committing_factory, "effis", T1) == 1

    t2 = T1 + timedelta(hours=4)
    await _update(committing_factory, "ba-1", at=t2, severity=4)
    assert await _match(committing_factory, "effis", t2) == 1

    # Deja de servirse: se cierra en silencio.
    t3 = t2 + timedelta(hours=4)
    await _update(committing_factory, "ba-1", at=t3, ends_at=t3)
    assert await _match(committing_factory, "effis", t3) == 0

    assert await _deliveries(committing_factory, sub) == [("opened", 3, 1), ("escalated", 4, 1)]


async def test_filtros_de_suscripcion(committing_factory: async_sessionmaker) -> None:
    exigente = await _subscribe(
        committing_factory, "province:30", types=["weather_warning"], severity_min=3
    )
    otro_tipo = await _subscribe(committing_factory, "province:30", types=["earthquake"])
    pausada = await _subscribe(
        committing_factory, "province:30", types=["weather_warning"], status="paused"
    )
    a = await _subscribe(committing_factory, "province:30", types=["weather_warning"])
    b = await _subscribe(committing_factory, "bbox:-1.5,37.9,-0.9,38.3", types=["weather_warning"])

    await _insert(
        committing_factory,
        at=T1,
        wkt=VEGA,
        **_warning("w1", "amarillo", T1 + timedelta(hours=6)),
    )
    assert await _match(committing_factory, "aemet", T1) == 2

    for silent in (exigente, otro_tipo, pausada):
        assert await _deliveries(committing_factory, silent) == []
    # Cada suscripcion lleva sus propios episodios.
    assert await _deliveries(committing_factory, a) == [("opened", 2, 1)]
    assert await _deliveries(committing_factory, b) == [("opened", 2, 1)]


async def test_idempotente_y_en_desorden(committing_factory: async_sessionmaker) -> None:
    sub = await _subscribe(committing_factory, "province:30", types=["weather_warning"])
    expires = T1 + timedelta(hours=10)
    t2 = T1 + timedelta(minutes=30)
    await _insert(committing_factory, at=T1, wkt=VEGA, **_warning("w1", "amarillo", expires))
    await _insert(committing_factory, at=t2, wkt=VEGA, **_warning("w2", "amarillo", expires))
    await _update(committing_factory, "w1", at=t2, ends_at=t2 - timedelta(minutes=5))

    # El lote T2 llega antes que T1 (reintento del outbox) y T2 se repite.
    assert await _match(committing_factory, "aemet", t2) == 1
    assert await _match(committing_factory, "aemet", t2) == 0
    assert await _match(committing_factory, "aemet", T1) == 0

    assert await _deliveries(committing_factory, sub) == [("opened", 2, 1)]


async def test_sin_suscripciones_no_cruza(committing_factory: async_sessionmaker) -> None:
    await _insert(
        committing_factory, at=T1, wkt=VEGA, **_warning("w1", "amarillo", T1 + timedelta(hours=6))
    )
    assert await _match(committing_factory, "aemet", T1) == 0
