from app.core.channels.driver import ChannelSender
from app.core.config import settings


class _ChannelSenderRegistry:
    """Singleton swappable: produccion construye el driver segun settings de
    forma perezosa; los tests registran un fake y hacen reset() al salir.
    """

    def __init__(self) -> None:
        self._sender: ChannelSender | None = None

    def register(self, sender: ChannelSender) -> None:
        self._sender = sender

    def get(self) -> ChannelSender:
        if self._sender is None:
            self._sender = self._build_from_settings()
        return self._sender

    def reset(self) -> None:
        self._sender = None

    @staticmethod
    def _build_from_settings() -> ChannelSender:
        if settings.NOTIFICATIONS_DRIVER == "fake":
            from app.core.channels.drivers.fake import FakeChannelSender

            return FakeChannelSender()
        from app.core.channels.drivers.http import HttpChannelSender

        return HttpChannelSender()


channel_sender_registry = _ChannelSenderRegistry()

__all__ = ["channel_sender_registry"]
