from app.core.aemet.driver import AemetClient
from app.core.config import settings


class _AemetClientRegistry:
    """Singleton swappable: produccion construye el driver segun settings de
    forma perezosa; los tests registran un fake y hacen reset() al salir.
    """

    def __init__(self) -> None:
        self._client: AemetClient | None = None

    def register(self, client: AemetClient) -> None:
        self._client = client

    def get(self) -> AemetClient:
        if self._client is None:
            self._client = self._build_from_settings()
        return self._client

    def reset(self) -> None:
        self._client = None

    @staticmethod
    def _build_from_settings() -> AemetClient:
        if settings.AEMET_DRIVER == "fake":
            from app.core.aemet.drivers.fake import AemetFakeClient

            return AemetFakeClient()
        from app.core.aemet.drivers.http import AemetHttpClient

        # El validador de settings garantiza que con AEMET_DRIVER=http la
        # key existe; aqui no hay caso vacio que manejar.
        return AemetHttpClient(api_key=settings.AEMET_API_KEY)


aemet_client_registry = _AemetClientRegistry()

__all__ = ["aemet_client_registry"]
