from typing import Protocol, runtime_checkable

from app.core.ign.types import IgnRecord


@runtime_checkable
class IgnClient(Protocol):
    """Puerto del catalogo sismico del IGN.

    Un unico producto: el GeoRSS de los ultimos 10 dias. Cada poll re-sirve
    la ventana completa, y el IGN revisa sus analisis en continuo (magnitud
    y epicentro pueden cambiar dias despues del evento).
    """

    async def fetch_earthquakes(self) -> list[IgnRecord]: ...


__all__ = ["IgnClient"]
