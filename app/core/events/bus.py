import logging
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events.models import OutboxEventORM

logger = logging.getLogger(__name__)


class EventBus:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def publish(
        self,
        event_type: str,
        payload: dict[str, Any],
        *,
        aggregate_id: uuid.UUID | None = None,
        correlation_id: uuid.UUID | None = None,
    ) -> OutboxEventORM:
        """Inserta el evento en el outbox dentro de la transaccion actual.

        NO hace commit: el dueno de la sesion decide la frontera. El worker
        lo recoge en su siguiente poll.
        """
        event = OutboxEventORM(
            event_type=event_type,
            payload=payload,
            aggregate_id=aggregate_id,
            correlation_id=correlation_id,
        )
        self.session.add(event)
        await self.session.flush()
        await self.session.refresh(event)

        logger.info("Published event %s (id=%s)", event_type, event.id)
        return event
