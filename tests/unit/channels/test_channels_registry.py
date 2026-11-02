import pytest

from app.core.channels.drivers.fake import FakeChannelSender
from app.core.channels.drivers.http import HttpChannelSender
from app.core.channels.registry import channel_sender_registry
from app.core.channels.types import ChannelError, NtfyMessage
from app.core.config import settings


@pytest.fixture(autouse=True)
def fresh_registry():
    channel_sender_registry.reset()
    yield
    channel_sender_registry.reset()


def test_construye_segun_el_driver(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "NOTIFICATIONS_DRIVER", "fake")
    assert isinstance(channel_sender_registry.get(), FakeChannelSender)

    channel_sender_registry.reset()
    monkeypatch.setattr(settings, "NOTIFICATIONS_DRIVER", "http")
    assert isinstance(channel_sender_registry.get(), HttpChannelSender)


def test_register_sustituye_y_reset_lo_retira() -> None:
    fake = FakeChannelSender()
    channel_sender_registry.register(fake)
    assert channel_sender_registry.get() is fake
    channel_sender_registry.reset()
    assert channel_sender_registry.get() is not fake


async def test_fake_guarda_lo_enviado_y_simula_caidas() -> None:
    fake = FakeChannelSender()
    message = NtfyMessage(title="t", body="b")
    await fake.send_ntfy(server="https://ntfy.sh", topic="topic", message=message)
    await fake.send_webhook(url="https://h.example", key="k", body=b"{}")
    await fake.check_endpoint("https://h.example")
    assert fake.ntfy_sent == [("https://ntfy.sh", "topic", message)]
    assert fake.webhook_sent == [("https://h.example", "k", b"{}")]

    fake.fail = True
    with pytest.raises(ChannelError):
        await fake.send_ntfy(server="https://ntfy.sh", topic="topic", message=message)
    with pytest.raises(ChannelError):
        await fake.send_webhook(url="https://h.example", key="k", body=b"{}")
    with pytest.raises(ChannelError):
        await fake.check_endpoint("http://h.example")
