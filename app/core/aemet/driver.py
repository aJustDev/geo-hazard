from typing import Protocol, runtime_checkable

from app.core.aemet.types import AemetWarning


@runtime_checkable
class AemetClient(Protocol):
    """Puerto de los avisos meteorologicos de AEMET (Meteoalerta).

    Un unico producto: el boletin "ultimo elaborado" para toda Espana, que
    contiene el set COMPLETO de avisos en vigor (un CAP por aviso y zona).
    Sincronizar es reconciliar contra ese set, no pedir novedades.
    """

    async def fetch_warnings(self) -> list[AemetWarning]: ...


__all__ = ["AemetClient"]
