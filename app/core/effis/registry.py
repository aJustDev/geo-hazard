from app.core.config import settings
from app.core.effis.driver import EffisClient


class _EffisClientRegistry:
    """Singleton swappable: produccion construye el driver segun settings de
    forma perezosa; los tests registran un fake y hacen reset() al salir.
    """

    def __init__(self) -> None:
        self._client: EffisClient | None = None

    def register(self, client: EffisClient) -> None:
        self._client = client

    def get(self) -> EffisClient:
        if self._client is None:
            self._client = self._build_from_settings()
        return self._client

    def reset(self) -> None:
        self._client = None

    @staticmethod
    def _build_from_settings() -> EffisClient:
        if settings.EFFIS_DRIVER == "fake":
            from app.core.effis.drivers.fake import EffisFakeClient

            return EffisFakeClient()
        from app.core.effis.drivers.http import EffisHttpClient

        return EffisHttpClient()


effis_client_registry = _EffisClientRegistry()

__all__ = ["effis_client_registry"]
