from typing import Protocol, runtime_checkable

from app.core.channels.types import NtfyMessage


@runtime_checkable
class ChannelSender(Protocol):
    """Puerto de salida de los avisos. Lanza ChannelError si no se entrega."""

    async def check_endpoint(self, url: str) -> None:
        """Valida un endpoint antes de guardarlo (https y host publico)."""
        ...

    async def send_ntfy(self, *, server: str, topic: str, message: NtfyMessage) -> None: ...

    async def send_webhook(self, *, url: str, key: str, body: bytes) -> None: ...


__all__ = ["ChannelSender"]
