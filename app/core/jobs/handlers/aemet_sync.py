"""Job recurrente: sincroniza los avisos CAP de AEMET Meteoalerta.

Sembrado con intervalo 1800s (30 min): AEMET elabora boletines unas pocas
veces al dia y la API opendata tiene cuota; pollear mas rapido gastaria
cuota para re-servir contenido identico que el content_hash descartaria.
"""

import logging

from app.core.aemet.exceptions import AemetTransientError
from app.core.aemet.registry import aemet_client_registry
from app.core.db import async_session_factory
from app.core.events.bus import EventBus
from app.core.jobs.registry import job_registry
from app.hazards.repos.hazard_event import HazardEventRepo
from app.hazards.repos.sync_state import SourceSyncStateRepo
from app.hazards.use_cases.sync_aemet import SOURCE, SyncAemetUseCase

logger = logging.getLogger(__name__)


@job_registry.register("aemet_sync")
async def aemet_sync() -> None:
    client = aemet_client_registry.get()
    async with async_session_factory() as session:
        use_case = SyncAemetUseCase(
            repo=HazardEventRepo(session),
            sync_state=SourceSyncStateRepo(session),
            event_bus=EventBus(session),
        )
        try:
            await use_case.execute(client=client)
        except AemetTransientError as exc:
            # Fuente caida o cuota agotada: no es fallo del job. Se descarta
            # la transaccion del lote pero el fallo queda contabilizado en su
            # propia sesion (sobrevive al rollback) para alertar por rachas.
            await session.rollback()
            logger.warning("aemet sync skipped, source unavailable: %s", exc)
            async with async_session_factory() as bookkeeping:
                await SourceSyncStateRepo(bookkeeping).record_failure(SOURCE, str(exc))
                await bookkeeping.commit()
            return
        await session.commit()
