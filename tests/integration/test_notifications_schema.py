"""Esquema de los avisos (ADR-0021) contra PostGIS real: geometria resuelta
de cada tipo de area y las restricciones que protegen el modelo."""

import math
import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions.exceptions import NotFoundError
from app.hazards.models import ProvinceORM
from app.notifications.models import (
    NotificationDeliveryORM,
    NotificationEpisodeORM,
    SubscriptionORM,
    WatchAreaORM,
)
from app.notifications.repos.watch_area import WatchAreaRepo
from app.notifications.services.areas import bbox_area, circle_area, province_area

pytestmark = [pytest.mark.integration, pytest.mark.asyncio(loop_scope="session")]

NOW = datetime(2026, 11, 2, 12, 0, tzinfo=UTC)


async def _geometry_type(session: AsyncSession, area: WatchAreaORM) -> str:
    return (
        await session.execute(
            select(func.GeometryType(WatchAreaORM.geom)).where(WatchAreaORM.id == area.id)
        )
    ).scalar_one()


async def test_area_provincia_copia_su_geometria(db_session: AsyncSession) -> None:
    area = await WatchAreaRepo(db_session).create_province(province_area("30"))

    assert area.kind == "province"
    assert area.label == "Murcia"
    assert area.params == {"code": "30"}
    same = (
        await db_session.execute(
            select(func.ST_Equals(WatchAreaORM.geom, ProvinceORM.geom))
            .join(ProvinceORM, ProvinceORM.code == "30")
            .where(WatchAreaORM.id == area.id)
        )
    ).scalar_one()
    assert same


async def test_area_provincia_inexistente(db_session: AsyncSession) -> None:
    with pytest.raises(NotFoundError, match="province"):
        await WatchAreaRepo(db_session).create_province(province_area("99"))


async def test_area_bbox_es_multipoligono(db_session: AsyncSession) -> None:
    area = await WatchAreaRepo(db_session).create_bbox(bbox_area("-1.5,37.5,-0.7,38.0"))

    assert await _geometry_type(db_session, area) == "MULTIPOLYGON"
    assert area.params == {"bbox": [-1.5, 37.5, -0.7, 38.0]}
    inside = (
        await db_session.execute(
            select(
                func.ST_Intersects(
                    WatchAreaORM.geom, func.ST_SetSRID(func.ST_MakePoint(-1.0, 37.7), 4326)
                )
            ).where(WatchAreaORM.id == area.id)
        )
    ).scalar_one()
    assert inside


@pytest.mark.parametrize(
    "raw",
    [
        "-0.99,37.62,30",  # Cartagena
        "-15.6,27.95,25",  # Gran Canaria: fuera de la zona UTM 30
    ],
)
async def test_area_circulo_con_radio_exacto(db_session: AsyncSession, raw: str) -> None:
    spec = circle_area(raw)
    area = await WatchAreaRepo(db_session).create_circle(spec)

    assert await _geometry_type(db_session, area) == "MULTIPOLYGON"
    area_m2 = (
        await db_session.execute(
            select(func.ST_Area(func.Geography(WatchAreaORM.geom))).where(
                WatchAreaORM.id == area.id
            )
        )
    ).scalar_one()
    assert area_m2 == pytest.approx(math.pi * spec.radius_m**2, rel=0.02)


async def _subscription(session: AsyncSession, **overrides: Any) -> SubscriptionORM:
    area = await WatchAreaRepo(session).create_bbox(bbox_area("-1.5,37.5,-0.7,38.0"))
    fields: dict[str, Any] = {
        "watch_area_id": area.id,
        "hazard_types": ["earthquake"],
        "severity_min": 2,
        "channel": "ntfy",
        "endpoint": "https://ntfy.sh",
        "credential": "geohazard-topic",
        **overrides,
    }
    subscription = SubscriptionORM(**fields)
    session.add(subscription)
    await session.flush()
    return subscription


async def test_suscripcion_valida_con_defaults(db_session: AsyncSession) -> None:
    subscription = await _subscription(db_session)
    await db_session.refresh(subscription)
    assert subscription.status == "active"
    assert subscription.consecutive_failures == 0


@pytest.mark.parametrize(
    "overrides",
    [
        {"hazard_types": []},
        {"hazard_types": ["volcano"]},
        {"severity_min": 0},
        {"severity_min": 5},
        {"channel": "email"},
        {"endpoint": "http://ntfy.sh"},
        {"status": "deleted"},
    ],
)
async def test_restricciones_de_suscripcion(
    db_session: AsyncSession, overrides: dict[str, Any]
) -> None:
    async with db_session.begin_nested():
        with pytest.raises(IntegrityError):
            await _subscription(db_session, **overrides)


def _episode(subscription_id: uuid.UUID, **overrides: Any) -> NotificationEpisodeORM:
    fields: dict[str, Any] = {
        "subscription_id": subscription_id,
        "key": "aemet:TO",
        "notified_severity": 2,
        "opened_at": NOW,
        "last_matched_at": NOW,
        **overrides,
    }
    return NotificationEpisodeORM(**fields)


async def test_un_solo_episodio_abierto_por_clave(db_session: AsyncSession) -> None:
    subscription = await _subscription(db_session)
    db_session.add(_episode(subscription.id, closed_at=NOW))
    db_session.add(_episode(subscription.id))
    await db_session.flush()  # uno cerrado y uno abierto conviven

    async with db_session.begin_nested():
        db_session.add(_episode(subscription.id))
        with pytest.raises(IntegrityError):
            await db_session.flush()


async def test_una_entrega_por_episodio_y_severidad(db_session: AsyncSession) -> None:
    subscription = await _subscription(db_session)
    episode = _episode(subscription.id)
    db_session.add(episode)
    await db_session.flush()

    def delivery(severity: int) -> NotificationDeliveryORM:
        return NotificationDeliveryORM(
            subscription_id=subscription.id,
            episode_id=episode.id,
            severity=severity,
            reason="opened",
            items=[],
            item_count=0,
        )

    db_session.add_all([delivery(2), delivery(3)])
    await db_session.flush()

    async with db_session.begin_nested():
        db_session.add(delivery(3))
        with pytest.raises(IntegrityError):
            await db_session.flush()


async def test_area_con_suscripcion_no_se_borra(db_session: AsyncSession) -> None:
    subscription = await _subscription(db_session)
    area = await db_session.get(WatchAreaORM, subscription.watch_area_id)

    async with db_session.begin_nested():
        await db_session.delete(area)
        with pytest.raises(IntegrityError):
            await db_session.flush()
