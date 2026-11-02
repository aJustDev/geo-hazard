"""Job de entrega de avisos (ADR-0021) contra PostGIS real, con el canal fake.
Las entregas se insertan a mano: el matching tiene sus propios tests."""

import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.channels.drivers.fake import FakeChannelSender
from app.core.config import settings
from app.core.jobs.handlers import notifications_deliver as deliver_job
from app.core.jobs.models import ScheduledJobORM
from app.hazards.models import SourceSyncStateORM
from app.notifications.models import (
    NotificationDeliveryORM,
    NotificationEpisodeORM,
    SubscriptionORM,
)
from app.notifications.repos.watch_area import WatchAreaRepo
from app.notifications.services.areas import province_area
from app.notifications.use_cases.deliver import DeliverNotificationsUseCase

pytestmark = [pytest.mark.integration, pytest.mark.asyncio(loop_scope="session")]


def _feature(zone: str = "Vega del Segura") -> dict[str, Any]:
    return {
        "type": "Feature",
        "id": str(uuid.uuid4()),
        "geometry": {"type": "Point", "coordinates": [-1.1, 37.9]},
        "properties": {
            "source": "aemet",
            "hazard_type": "weather_warning",
            "severity": 2,
            "starts_at": "2026-11-04T13:00:00+00:00",
            "ends_at": "2026-11-04T20:59:59+00:00",
            "external_id": "cap-1",
            "attrs": {"level": "amarillo", "phenomenon": "TO;Tormentas", "area_desc": zone},
        },
    }


async def _subscription(
    factory: async_sessionmaker, *, channel: str = "ntfy", **fields: Any
) -> uuid.UUID:
    async with factory() as session:
        area = await WatchAreaRepo(session).create_province(province_area("30"))
        subscription = SubscriptionORM(
            watch_area_id=area.id,
            hazard_types=["weather_warning"],
            severity_min=2,
            channel=channel,
            endpoint="https://ntfy.sh" if channel == "ntfy" else "https://hooks.example.com/x",
            credential="geohazard-topic" if channel == "ntfy" else "k" * 64,
            **fields,
        )
        session.add(subscription)
        await session.commit()
        return subscription.id


async def _pending(
    factory: async_sessionmaker, subscription_id: uuid.UUID, *, severity: int = 2, **fields: Any
) -> uuid.UUID:
    now = datetime.now(UTC)
    async with factory() as session:
        episode = NotificationEpisodeORM(
            subscription_id=subscription_id,
            key=f"aemet:{uuid.uuid4().hex[:6]}",
            notified_severity=severity,
            opened_at=now,
            last_matched_at=now,
        )
        session.add(episode)
        await session.flush()
        delivery = NotificationDeliveryORM(
            subscription_id=subscription_id,
            episode_id=episode.id,
            severity=severity,
            reason="opened",
            items=[_feature()],
            item_count=1,
            **fields,
        )
        session.add(delivery)
        await session.commit()
        return delivery.id


async def _deliver(factory: async_sessionmaker, sender: FakeChannelSender):
    return await DeliverNotificationsUseCase(session_factory=factory, sender=sender).execute()


async def _get(factory: async_sessionmaker, model: type, id_: uuid.UUID) -> Any:
    async with factory() as session:
        return await session.get(model, id_)


async def _set(factory: async_sessionmaker, subscription_id: uuid.UUID, **values: Any) -> None:
    async with factory() as session:
        await session.execute(
            update(SubscriptionORM).where(SubscriptionORM.id == subscription_id).values(**values)
        )
        await session.commit()


async def test_pendientes_salen_en_un_solo_mensaje(committing_factory: async_sessionmaker) -> None:
    subscription_id = await _subscription(committing_factory)
    ids = [await _pending(committing_factory, subscription_id, severity=s) for s in (2, 3, 2)]
    sender = FakeChannelSender()

    report = await _deliver(committing_factory, sender)

    assert report.sent == 1
    (server, topic, message) = sender.ntfy_sent[0]
    assert (server, topic) == ("https://ntfy.sh", "geohazard-topic")
    assert message.title == "3 avisos en Murcia"
    assert message.priority == 4
    deliveries = [await _get(committing_factory, NotificationDeliveryORM, i) for i in ids]
    assert {d.status for d in deliveries} == {"sent"}
    assert len({d.message_id for d in deliveries}) == 1
    assert all(d.attempts == 1 for d in deliveries)
    subscription = await _get(committing_factory, SubscriptionORM, subscription_id)
    assert subscription.last_sent_at is not None
    assert subscription.retry_at is None

    # Nada pendiente: la siguiente ejecucion no envia.
    assert (await _deliver(committing_factory, sender)).sent == 0
    assert len(sender.ntfy_sent) == 1


async def test_intervalo_minimo_retiene_y_luego_agrupa(
    committing_factory: async_sessionmaker,
) -> None:
    subscription_id = await _subscription(committing_factory)
    await _pending(committing_factory, subscription_id)
    sender = FakeChannelSender()
    await _set(committing_factory, subscription_id, last_sent_at=datetime.now(UTC))

    assert (await _deliver(committing_factory, sender)).sent == 0

    await _set(
        committing_factory,
        subscription_id,
        last_sent_at=datetime.now(UTC)
        - timedelta(seconds=settings.NOTIFICATIONS_MIN_INTERVAL_SECONDS + 1),
    )
    assert (await _deliver(committing_factory, sender)).sent == 1


async def test_fallo_aplaza_con_backoff_y_sin_url_en_el_error(
    committing_factory: async_sessionmaker,
) -> None:
    subscription_id = await _subscription(committing_factory)
    delivery_id = await _pending(committing_factory, subscription_id)
    sender = FakeChannelSender(fail=True)

    report = await _deliver(committing_factory, sender)

    assert report.failed == 1
    subscription = await _get(committing_factory, SubscriptionORM, subscription_id)
    assert subscription.consecutive_failures == 1
    assert subscription.failing_since is not None
    assert subscription.retry_at > datetime.now(UTC)
    assert subscription.last_error == "fake channel down"
    delivery = await _get(committing_factory, NotificationDeliveryORM, delivery_id)
    assert (delivery.status, delivery.attempts) == ("pending", 1)

    # En backoff: ni se intenta.
    assert (await _deliver(committing_factory, sender)).failed == 0


async def test_un_dia_fallando_pausa_y_descarta_pendientes(
    committing_factory: async_sessionmaker,
) -> None:
    subscription_id = await _subscription(committing_factory)
    delivery_id = await _pending(committing_factory, subscription_id)
    await _set(
        committing_factory,
        subscription_id,
        consecutive_failures=20,
        failing_since=datetime.now(UTC) - timedelta(hours=25),
    )

    report = await _deliver(committing_factory, FakeChannelSender(fail=True))

    assert report.paused == 1
    subscription = await _get(committing_factory, SubscriptionORM, subscription_id)
    assert subscription.status == "paused"
    assert "fake channel down" in subscription.paused_reason
    delivery = await _get(committing_factory, NotificationDeliveryORM, delivery_id)
    assert delivery.status == "failed"


async def test_suscripcion_pausada_no_se_reclama(committing_factory: async_sessionmaker) -> None:
    subscription_id = await _subscription(committing_factory, status="paused")
    await _pending(committing_factory, subscription_id)
    sender = FakeChannelSender()

    assert (await _deliver(committing_factory, sender)).sent == 0
    assert sender.ntfy_sent == []


async def test_presupuesto_agotado_envia_una_y_devuelve_el_resto(
    committing_factory: async_sessionmaker, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "NOTIFICATIONS_DELIVER_BUDGET_SECONDS", 0)
    first = await _subscription(committing_factory)
    second = await _subscription(committing_factory)
    await _pending(committing_factory, first)
    await _pending(committing_factory, second)

    report = await _deliver(committing_factory, FakeChannelSender())

    assert (report.sent, report.skipped) == (1, 1)
    # La aplazada recupera su retry_at (NULL): entra en la siguiente.
    async with committing_factory() as session:
        retry = await session.execute(
            select(SubscriptionORM.retry_at).where(SubscriptionORM.id.in_([first, second]))
        )
        assert set(retry.scalars().all()) == {None}
    assert (await _deliver(committing_factory, FakeChannelSender())).sent == 1


async def test_caida_entre_enviar_y_registrar_reenvia_las_mismas(
    committing_factory: async_sessionmaker, monkeypatch: pytest.MonkeyPatch
) -> None:
    subscription_id = await _subscription(committing_factory, channel="webhook")
    delivery_id = await _pending(committing_factory, subscription_id)
    sender = FakeChannelSender()

    async def crash(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("proceso muerto")

    monkeypatch.setattr(DeliverNotificationsUseCase, "_record", staticmethod(crash))
    with pytest.raises(RuntimeError):
        await _deliver(committing_factory, sender)
    monkeypatch.undo()

    # Tras el backoff se reenvia con el mismo delivery_id: el receptor deduplica.
    await _set(committing_factory, subscription_id, retry_at=datetime.now(UTC))
    await _deliver(committing_factory, sender)
    ids = [json.loads(body)["items"][0]["delivery_id"] for _, _, body in sender.webhook_sent]
    assert ids == [str(delivery_id), str(delivery_id)]
    assert (await _get(committing_factory, NotificationDeliveryORM, delivery_id)).status == "sent"


async def test_webhook_lleva_el_sobre_y_la_clave(committing_factory: async_sessionmaker) -> None:
    subscription_id = await _subscription(committing_factory, channel="webhook")
    await _pending(committing_factory, subscription_id)
    sender = FakeChannelSender()

    await _deliver(committing_factory, sender)

    (url, key, body) = sender.webhook_sent[0]
    assert (url, key) == ("https://hooks.example.com/x", "k" * 64)
    envelope = json.loads(body)
    assert envelope["subscription_id"] == str(subscription_id)
    assert envelope["area"]["label"] == "Murcia"


async def test_avisa_de_su_fuente_degradada(committing_factory: async_sessionmaker) -> None:
    subscription_id = await _subscription(committing_factory)
    await _pending(committing_factory, subscription_id)
    async with committing_factory() as session:
        session.add(ScheduledJobORM(job_name="aemet_sync", interval_seconds=1800))
        session.add(
            SourceSyncStateORM(
                source="aemet",
                last_success_at=datetime.now(UTC) - timedelta(hours=6),
                consecutive_failures=12,
            )
        )
        await session.commit()
    sender = FakeChannelSender()

    await _deliver(committing_factory, sender)

    assert "sin datos recientes de AEMET" in sender.ntfy_sent[0][2].body


async def test_purga_lo_viejo_y_conserva_lo_pendiente(
    committing_factory: async_sessionmaker,
) -> None:
    subscription_id = await _subscription(committing_factory)
    old = datetime.now(UTC) - timedelta(days=settings.NOTIFICATIONS_RETENTION_DAYS + 1)
    sent_old = await _pending(committing_factory, subscription_id, status="sent", sent_at=old)
    pending_old = await _pending(committing_factory, subscription_id, severity=3)
    async with committing_factory() as session:
        await session.execute(
            update(NotificationEpisodeORM).values(last_matched_at=old, opened_at=old)
        )
        await session.commit()
    await _set(committing_factory, subscription_id, status="paused")  # que no se envie

    report = await _deliver(committing_factory, FakeChannelSender())

    assert (report.purged_deliveries, report.purged_episodes) == (1, 1)
    assert await _get(committing_factory, NotificationDeliveryORM, sent_old) is None
    assert await _get(committing_factory, NotificationDeliveryORM, pending_old) is not None
    async with committing_factory() as session:
        episodes = await session.execute(select(func.count(NotificationEpisodeORM.id)))
        assert episodes.scalar_one() == 1


async def test_job_usa_el_canal_del_registry(
    committing_factory: async_sessionmaker, monkeypatch: pytest.MonkeyPatch
) -> None:
    subscription_id = await _subscription(committing_factory)
    await _pending(committing_factory, subscription_id)
    sender = FakeChannelSender()
    monkeypatch.setattr(deliver_job, "async_session_factory", committing_factory)
    monkeypatch.setattr(deliver_job.channel_sender_registry, "_sender", sender)

    await deliver_job.notifications_deliver()

    assert len(sender.ntfy_sent) == 1
