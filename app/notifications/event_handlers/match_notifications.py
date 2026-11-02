"""Handler del outbox: cruza cada lote ingerido con las suscripciones
(ADR-0021). Corre despues de export_geoparquet (orden de import en
db_registry); el envio lo hace aparte el job notifications_deliver."""

import logging
from datetime import datetime
from typing import Any

from app.core.db import async_session_factory
from app.core.events.dispatcher import dispatcher
from app.hazards.events import BATCH_INGESTED
from app.notifications.use_cases.match_batch import MatchBatchUseCase

logger = logging.getLogger(__name__)


@dispatcher.register(BATCH_INGESTED)
async def match_notifications(payload: dict[str, Any]) -> None:
    raw_batch_at = payload.get("batch_at")
    if raw_batch_at is None:
        # Evento publicado antes de que el lote llevara su marca.
        logger.info("notifications: %s batch without batch_at skipped", payload.get("source"))
        return
    async with async_session_factory() as session:
        created = await MatchBatchUseCase(session).execute(
            source=payload["source"], batch_at=datetime.fromisoformat(raw_batch_at)
        )
        await session.commit()
    if created:
        logger.info("notifications: %d new from %s batch", created, payload["source"])
