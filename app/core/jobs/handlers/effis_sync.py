"""Job recurrente: sincroniza el catalogo de incendios EFFIS.

Sembrado en la migracion de hazard_events con intervalo 14400s (4h): EFFIS
actualiza sus capas unas 6 veces al dia; pollear mas rapido solo re-serviria
contenido identico que el content_hash descartaria igualmente.
"""

import logging

from app.core.db import async_session_factory
from app.core.effis.exceptions import EffisTransientError
from app.core.effis.registry import effis_client_registry
from app.core.events.bus import EventBus
from app.core.jobs.registry import job_registry
from app.hazards.repos.hazard_event import HazardEventRepo
from app.hazards.repos.sync_state import SourceSyncStateRepo
from app.hazards.use_cases.sync_effis import SOURCE, SyncEffisUseCase

logger = logging.getLogger(__name__)


@job_registry.register("effis_sync")
async def effis_sync() -> None:
    client = effis_client_registry.get()
    async with async_session_factory() as session:
        use_case = SyncEffisUseCase(
            repo=HazardEventRepo(session),
            sync_state=SourceSyncStateRepo(session),
            event_bus=EventBus(session),
        )
        try:
            await use_case.execute(client=client)
        except EffisTransientError as exc:
            # Fuente caida: no es fallo del job. Se descarta la transaccion
            # del lote pero el fallo queda contabilizado en su propia sesion
            # (sobrevive al rollback) para poder alertar por rachas.
            await session.rollback()
            logger.warning("effis sync skipped, source unavailable: %s", exc)
            async with async_session_factory() as bookkeeping:
                await SourceSyncStateRepo(bookkeeping).record_failure(SOURCE, str(exc))
                await bookkeeping.commit()
            return
        await session.commit()
