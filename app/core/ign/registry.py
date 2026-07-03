from app.core.config import settings
from app.core.ign.driver import IgnClient


class _IgnClientRegistry:
    """Singleton swappable: produccion construye el driver segun settings de
    forma perezosa; los tests registran un fake y hacen reset() al salir.
    """

    def __init__(self) -> None:
        self._client: IgnClient | None = None

    def register(self, client: IgnClient) -> None:
        self._client = client

    def get(self) -> IgnClient:
        if self._client is None:
            self._client = self._build_from_settings()
        return self._client

    def reset(self) -> None:
        self._client = None

    @staticmethod
    def _build_from_settings() -> IgnClient:
        if settings.IGN_DRIVER == "fake":
            from app.core.ign.drivers.fake import IgnFakeClient

            return IgnFakeClient()
        from app.core.ign.drivers.http import IgnHttpClient

        return IgnHttpClient()


ign_client_registry = _IgnClientRegistry()

__all__ = ["ign_client_registry"]
