"""Job recurrente: sincroniza el catalogo sismico del IGN.

Sembrado con intervalo 900s (15 min): el feed es barato (publico, sin auth,
~15 KB) y un sismo relevante debe aparecer en la API con poca latencia; la
ventana de 10 dias hace que cualquier poll perdido se recupere solo.
"""

import logging

from app.core.db import async_session_factory
from app.core.events.bus import EventBus
from app.core.ign.exceptions import IgnTransientError
from app.core.ign.registry import ign_client_registry
from app.core.jobs.registry import job_registry
from app.hazards.repos.hazard_event import HazardEventRepo
from app.hazards.repos.sync_state import SourceSyncStateRepo
from app.hazards.use_cases.sync_ign import SOURCE, SyncIgnUseCase

logger = logging.getLogger(__name__)


@job_registry.register("ign_sync")
async def ign_sync() -> None:
    client = ign_client_registry.get()
    async with async_session_factory() as session:
        use_case = SyncIgnUseCase(
            repo=HazardEventRepo(session),
            sync_state=SourceSyncStateRepo(session),
            event_bus=EventBus(session),
        )
        try:
            await use_case.execute(client=client)
        except IgnTransientError as exc:
            # Fuente caida: no es fallo del job. Se descarta la transaccion
            # del lote pero el fallo queda contabilizado en su propia sesion
            # (sobrevive al rollback) para poder alertar por rachas.
            await session.rollback()
            logger.warning("ign sync skipped, source unavailable: %s", exc)
            async with async_session_factory() as bookkeeping:
                await SourceSyncStateRepo(bookkeeping).record_failure(SOURCE, str(exc))
                await bookkeeping.commit()
            return
        await session.commit()
