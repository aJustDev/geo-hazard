"""CLI de avisos (ADR-0021) contra PostGIS real, con el canal fake."""

import io
import json
import re
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.channels.drivers.fake import FakeChannelSender
from app.core.config import settings
from app.notifications.cli import run
from app.notifications.models import (
    NotificationDeliveryORM,
    NotificationEpisodeORM,
    SubscriptionORM,
    WatchAreaORM,
)

pytestmark = [pytest.mark.integration, pytest.mark.asyncio(loop_scope="session")]


async def _cli(
    factory: async_sessionmaker, sender: FakeChannelSender, *argv: str
) -> tuple[int, str]:
    out = io.StringIO()
    code = await run(list(argv), session_factory=factory, sender=sender, out=out)
    return code, out.getvalue()


def _created_id(output: str) -> uuid.UUID:
    match = re.search(r"Suscripcion creada: ([0-9a-f-]{36})", output)
    assert match, output
    return uuid.UUID(match.group(1))


ADD_MURCIA = (
    "add",
    "--province",
    "30",
    "--types",
    "weather_warning,earthquake,wildfire",
    "--severity-min",
    "2",
    "--ntfy",
)


async def test_alta_ntfy_muestra_el_topic_una_vez(committing_factory: async_sessionmaker) -> None:
    sender = FakeChannelSender()
    code, output = await _cli(committing_factory, sender, *ADD_MURCIA)

    assert code == 0
    topic = re.search(r"Topic ntfy \(no se vuelve a mostrar\): (\S+)", output).group(1)
    assert topic.startswith("geohazard-")
    subscription_id = _created_id(output)

    # Un circulo en Cartagena compartiendo el mismo topic sin teclearlo.
    code, output = await _cli(
        committing_factory,
        sender,
        "add",
        "--circle",
        "-0.99,37.62,30",
        "--label",
        "Cartagena",
        "--types",
        "earthquake",
        "--severity-min",
        "2",
        "--same-channel-as",
        str(subscription_id),
    )
    assert code == 0
    assert "compartido" in output
    async with committing_factory() as session:
        credentials = (await session.execute(select(SubscriptionORM.credential))).scalars().all()
    assert credentials == [topic, topic]

    code, listing = await _cli(committing_factory, sender, "list")
    assert code == 0
    assert topic not in listing
    assert f"...{topic[-4:]}" in listing
    assert "area: Murcia" in listing
    assert "area: Cartagena" in listing


async def test_alta_webhook_genera_clave_y_valida_https(
    committing_factory: async_sessionmaker,
) -> None:
    sender = FakeChannelSender()
    base = ("add", "--province", "30", "--types", "earthquake", "--severity-min", "3")

    code, output = await _cli(committing_factory, sender, *base, "--webhook", "http://h.example")
    assert code == 1
    assert "https" in output

    code, output = await _cli(
        committing_factory, sender, *base, "--webhook", "https://h.example/hook"
    )
    assert code == 0
    assert re.search(r"Clave HMAC del webhook \(no se vuelve a mostrar\): [0-9a-f]{64}", output)


@pytest.mark.parametrize(
    "argv",
    [
        ("add", "--province", "99", "--types", "earthquake", "--severity-min", "2", "--ntfy"),
        (
            "add",
            "--circle",
            "-0.99,37.62,500",
            "--types",
            "earthquake",
            "--severity-min",
            "2",
            "--ntfy",
        ),
        ("add", "--province", "30", "--types", "volcano", "--severity-min", "2", "--ntfy"),
        ("pause", str(uuid.uuid4())),
    ],
)
async def test_errores_de_entrada(committing_factory: async_sessionmaker, argv) -> None:
    code, output = await _cli(committing_factory, FakeChannelSender(), *argv)
    assert code == 1
    assert output.startswith("error: ")


async def test_fake_fuera_de_local_se_niega(
    committing_factory: async_sessionmaker, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    code, output = await _cli(committing_factory, FakeChannelSender(), *ADD_MURCIA)
    assert code == 1
    assert "NOTIFICATIONS_DRIVER=fake" in output


async def test_pausar_reanudar_y_borrar(committing_factory: async_sessionmaker) -> None:
    sender = FakeChannelSender()
    subscription_id = _created_id((await _cli(committing_factory, sender, *ADD_MURCIA))[1])
    now = datetime.now(UTC)
    async with committing_factory() as session:
        episode = NotificationEpisodeORM(
            subscription_id=subscription_id,
            key="aemet:TO",
            notified_severity=2,
            opened_at=now,
            last_matched_at=now,
        )
        session.add(episode)
        await session.flush()
        session.add(
            NotificationDeliveryORM(
                subscription_id=subscription_id,
                episode_id=episode.id,
                severity=2,
                reason="opened",
                items=[],
                item_count=0,
            )
        )
        await session.commit()

    assert (await _cli(committing_factory, sender, "pause", str(subscription_id)))[0] == 0
    async with committing_factory() as session:
        subscription = await session.get(SubscriptionORM, subscription_id)
        assert subscription.status == "paused"
        statuses = (await session.execute(select(NotificationDeliveryORM.status))).scalars().all()
        assert statuses == ["failed"]

    assert (await _cli(committing_factory, sender, "resume", str(subscription_id)))[0] == 0
    async with committing_factory() as session:
        subscription = await session.get(SubscriptionORM, subscription_id)
        assert (subscription.status, subscription.paused_reason) == ("active", None)

    assert (await _cli(committing_factory, sender, "remove", str(subscription_id)))[0] == 0
    async with committing_factory() as session:
        assert await session.get(SubscriptionORM, subscription_id) is None
        assert (await session.execute(select(WatchAreaORM))).first() is None


async def test_prueba_por_ntfy_y_webhook(committing_factory: async_sessionmaker) -> None:
    sender = FakeChannelSender()
    ntfy_id = _created_id((await _cli(committing_factory, sender, *ADD_MURCIA))[1])
    webhook_id = _created_id(
        (
            await _cli(
                committing_factory,
                sender,
                "add",
                "--bbox",
                "-1.5,37.5,-0.7,38.0",
                "--types",
                "earthquake",
                "--severity-min",
                "2",
                "--webhook",
                "https://h.example/hook",
            )
        )[1]
    )

    assert (await _cli(committing_factory, sender, "test", str(ntfy_id)))[0] == 0
    assert (await _cli(committing_factory, sender, "test", str(webhook_id)))[0] == 0

    assert sender.ntfy_sent[0][2].title == "geo-hazard: prueba - Murcia"
    envelope = json.loads(sender.webhook_sent[0][2])
    assert envelope["items"] == []
    assert envelope["subscription_id"] == str(webhook_id)

    sender.fail = True
    code, output = await _cli(committing_factory, sender, "test", str(ntfy_id))
    assert (code, output) == (1, "error: fake channel down\n")


async def test_estadisticas_y_provincias(committing_factory: async_sessionmaker) -> None:
    sender = FakeChannelSender()
    subscription_id = _created_id((await _cli(committing_factory, sender, *ADD_MURCIA))[1])
    now = datetime.now(UTC)
    message_id = uuid.uuid4()
    async with committing_factory() as session:
        for severity in (2, 3):
            episode = NotificationEpisodeORM(
                subscription_id=subscription_id,
                key=f"k{severity}",
                notified_severity=severity,
                opened_at=now,
                last_matched_at=now,
            )
            session.add(episode)
            await session.flush()
            session.add(
                NotificationDeliveryORM(
                    subscription_id=subscription_id,
                    episode_id=episode.id,
                    severity=severity,
                    reason="opened",
                    items=[],
                    item_count=0,
                    status="sent",
                    sent_at=now,
                    message_id=message_id,
                )
            )
        await session.commit()

    code, output = await _cli(committing_factory, sender, "stats")
    assert code == 0
    assert "Murcia" in output
    assert "1 mensajes, 2 avisos" in output

    code, output = await _cli(committing_factory, sender, "provinces")
    assert code == 0
    assert len(output.splitlines()) == 52
    assert "30  Murcia" in output.splitlines()
