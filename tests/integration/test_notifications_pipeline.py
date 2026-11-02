"""Avisos de punta a punta (ADR-0021): sync AEMET -> outbox -> cruce ->
job de entrega -> canal. Un segundo boletin con un Update al mismo nivel no
vuelve a avisar."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core import config
from app.core.aemet.drivers.fake import AemetFakeClient
from app.core.aemet.registry import aemet_client_registry
from app.core.aemet.types import MSG_TYPE_ALERT, MSG_TYPE_UPDATE, AemetWarning
from app.core.channels.drivers.fake import FakeChannelSender
from app.core.channels.registry import channel_sender_registry
from app.core.events import worker as events_worker_module
from app.core.events.worker import OutboxWorker
from app.core.jobs.handlers import aemet_sync as aemet_sync_module
from app.core.jobs.handlers import notifications_deliver as deliver_module
from app.hazards.event_handlers import export_geoparquet as export_module
from app.notifications.event_handlers import match_notifications as match_module
from app.notifications.models import SubscriptionORM
from app.notifications.repos.watch_area import WatchAreaRepo
from app.notifications.services.areas import province_area

pytestmark = [pytest.mark.integration, pytest.mark.asyncio(loop_scope="session")]

# Vega del Segura en formato CAP: "lat,lon" separados por espacios.
VEGA_CAP = "38.0,-1.3 38.0,-1.0 38.2,-1.0 38.2,-1.3 38.0,-1.3"


@pytest.fixture
def sender(committing_factory: async_sessionmaker, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    for module in (
        aemet_sync_module,
        events_worker_module,
        export_module,
        match_module,
        deliver_module,
    ):
        monkeypatch.setattr(module, "async_session_factory", committing_factory)
    monkeypatch.setattr(config.settings, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(config.settings, "NOTIFICATIONS_MIN_INTERVAL_SECONDS", 0)
    (tmp_path / "exports").mkdir()
    fake = FakeChannelSender()
    channel_sender_registry.register(fake)
    yield fake
    channel_sender_registry.reset()
    aemet_client_registry.reset()


def _warning(external_id: str, *, msg_type: str, sent: datetime, **kw) -> AemetWarning:
    now = datetime.now(UTC)
    return AemetWarning(
        external_id=external_id,
        msg_type=msg_type,
        sent=sent,
        event="Aviso de tormentas de nivel amarillo",
        phenomenon="TO;Tormentas",
        level="amarillo",
        onset=now,
        expires=now + timedelta(hours=6),
        polygon=VEGA_CAP,
        zone="733003",
        area_desc="Vega del Segura",
        **kw,
    )


async def _bulletin(warnings: list[AemetWarning]) -> None:
    aemet_client_registry.register(AemetFakeClient(warnings=warnings))
    await aemet_sync_module.aemet_sync()
    await OutboxWorker()._process_batch()
    await deliver_module.notifications_deliver()


async def test_aviso_llega_una_vez(
    committing_factory: async_sessionmaker, sender: FakeChannelSender
) -> None:
    async with committing_factory() as session:
        area = await WatchAreaRepo(session).create_province(province_area("30"))
        session.add(
            SubscriptionORM(
                watch_area_id=area.id,
                hazard_types=["weather_warning"],
                severity_min=2,
                channel="ntfy",
                endpoint="https://ntfy.sh",
                credential="geohazard-topic",
            )
        )
        await session.commit()

    now = datetime.now(UTC)
    await _bulletin([_warning("cap-1", msg_type=MSG_TYPE_ALERT, sent=now - timedelta(minutes=20))])

    assert len(sender.ntfy_sent) == 1
    message = sender.ntfy_sent[0][2]
    assert message.title == "Aviso amarillo por tormentas - Murcia"
    assert "Vega del Segura" in message.body

    # Boletin siguiente: AEMET sustituye el aviso por un Update al mismo nivel.
    update = _warning(
        "cap-2", msg_type=MSG_TYPE_UPDATE, sent=now - timedelta(minutes=2), references=("cap-1",)
    )
    await _bulletin([update])

    assert len(sender.ntfy_sent) == 1
