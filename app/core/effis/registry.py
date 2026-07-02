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
        # Bloqueado en la captura del payload real del WFS (docs/sources.md):
        # el backend de capas del JRC fallaba el dia del spike y el esquema de
        # propiedades sigue sin verificar. Sin muestra real, no hay parser.
        raise NotImplementedError(
            "EFFIS_DRIVER='http' pending real WFS payload capture; see docs/sources.md"
        )


effis_client_registry = _EffisClientRegistry()

__all__ = ["effis_client_registry"]
