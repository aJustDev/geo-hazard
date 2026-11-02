import logging
from dataclasses import dataclass, field

from app.core.channels.types import ChannelError, NtfyMessage

logger = logging.getLogger(__name__)


@dataclass
class FakeChannelSender:
    """Driver sin red para dev y tests. Cumple el Protocol ChannelSender.

    Guarda lo enviado para que los tests lo inspeccionen; con `fail` puesto
    simula un canal caido. No loguea topics ni URLs: son credenciales.
    """

    fail: bool = False
    ntfy_sent: list[tuple[str, str, NtfyMessage]] = field(default_factory=list)
    webhook_sent: list[tuple[str, str, bytes]] = field(default_factory=list)

    async def check_endpoint(self, url: str) -> None:
        if not url.startswith("https://"):
            raise ChannelError("endpoint must be https")

    async def send_ntfy(self, *, server: str, topic: str, message: NtfyMessage) -> None:
        if self.fail:
            raise ChannelError("fake channel down")
        self.ntfy_sent.append((server, topic, message))
        logger.info("fake channel: ntfy message %r not sent", message.title)

    async def send_webhook(self, *, url: str, key: str, body: bytes) -> None:
        if self.fail:
            raise ChannelError("fake channel down")
        self.webhook_sent.append((url, key, body))
        logger.info("fake channel: webhook of %d bytes not sent", len(body))


__all__ = ["FakeChannelSender"]
