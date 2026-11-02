"""Job recurrente: entrega los avisos pendientes (ADR-0021).

Cada 60 s, sembrado por migracion. Comparte worker con los syncs, que se
ejecutan uno tras otro: el caso de uso se acota a un presupuesto de tiempo.
"""

import logging

from app.core.channels.registry import channel_sender_registry
from app.core.db import async_session_factory
from app.core.jobs.registry import job_registry
from app.notifications.use_cases.deliver import DeliverNotificationsUseCase

logger = logging.getLogger(__name__)


@job_registry.register("notifications_deliver")
async def notifications_deliver() -> None:
    report = await DeliverNotificationsUseCase(
        session_factory=async_session_factory, sender=channel_sender_registry.get()
    ).execute()
    if report.active:
        logger.info(
            "notifications: %d sent, %d failed, %d paused, %d deferred",
            report.sent,
            report.failed,
            report.paused,
            report.skipped,
        )
