import logging
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.channels.driver import ChannelSender
from app.core.channels.types import ChannelError
from app.core.config import settings
from app.notifications.repos.delivery import DeliveryRepo
from app.notifications.repos.source_status import degraded_sources
from app.notifications.schemas.delivery import ClaimedSubscription
from app.notifications.services.messages import render_ntfy, render_webhook

logger = logging.getLogger(__name__)

# Tope de suscripciones por ejecucion; el presupuesto de tiempo manda antes.
_MAX_SUBSCRIPTIONS_PER_RUN = 50


@dataclass(slots=True)
class DeliveryReport:
    sent: int = 0
    failed: int = 0
    paused: int = 0
    skipped: int = 0
    purged_deliveries: int = 0
    purged_episodes: int = 0

    @property
    def active(self) -> bool:
        return any((self.sent, self.failed, self.paused, self.skipped))


@dataclass(slots=True)
class _Outcome:
    claim: ClaimedSubscription
    message_id: uuid.UUID | None = None
    error: str | None = None
    skipped: bool = False


@dataclass(slots=True)
class DeliverNotificationsUseCase:
    """Envia un mensaje por suscripcion con todas sus entregas pendientes
    (ADR-0021).

    Excepcion documentada a "los casos de uso no commitean": este es dueno
    de sus tres transacciones porque el envio tiene que quedar FUERA de
    cualquiera de ellas (un webhook lento no puede retener locks). Reclamar
    y adelantar retry_at, enviar sin transaccion, y registrar el resultado.
    Entrega al menos una vez: si el proceso muere entre enviar y registrar,
    retry_at hace que se reenvie tras el backoff con los mismos ids.
    """

    session_factory: async_sessionmaker[AsyncSession]
    sender: ChannelSender

    async def execute(self) -> DeliveryReport:
        report = DeliveryReport()
        async with self.session_factory() as session:
            repo = DeliveryRepo(session)
            now = await repo.db_now()
            claims = await repo.claim(
                now,
                min_interval=timedelta(seconds=settings.NOTIFICATIONS_MIN_INTERVAL_SECONDS),
                limit=_MAX_SUBSCRIPTIONS_PER_RUN,
            )
            degraded = await degraded_sources(session, now=now) if claims else []
            await session.commit()

        outcomes = await self._send_all(claims, degraded)

        async with self.session_factory() as session:
            repo = DeliveryRepo(session)
            await self._record(repo, outcomes, report, now=await repo.db_now())
            report.purged_deliveries, report.purged_episodes = await repo.purge(
                await repo.db_now(),
                retention=timedelta(days=settings.NOTIFICATIONS_RETENTION_DAYS),
            )
            await session.commit()
        return report

    async def _send_all(
        self, claims: list[ClaimedSubscription], degraded: list[str]
    ) -> list[_Outcome]:
        outcomes: list[_Outcome] = []
        deadline = time.monotonic() + settings.NOTIFICATIONS_DELIVER_BUDGET_SECONDS
        for claim in claims:
            # Siempre se intenta al menos una: un presupuesto mal puesto no
            # puede dejar el canal mudo.
            if outcomes and time.monotonic() >= deadline:
                outcomes.append(_Outcome(claim, skipped=True))
                continue
            message_id = uuid.uuid4()
            try:
                await self._send(claim, degraded, message_id)
            except ChannelError as exc:
                logger.warning("notification for subscription %s failed: %s", claim.id, exc)
                outcomes.append(_Outcome(claim, error=str(exc)))
            else:
                outcomes.append(_Outcome(claim, message_id=message_id))
        return outcomes

    async def _send(
        self, claim: ClaimedSubscription, degraded: list[str], message_id: uuid.UUID
    ) -> None:
        if claim.channel == "ntfy":
            message = render_ntfy(
                claim,
                degraded,
                base_url=settings.NOTIFICATIONS_PUBLIC_BASE_URL,
                max_items=settings.NOTIFICATIONS_MAX_ITEMS_PER_MESSAGE,
            )
            await self.sender.send_ntfy(
                server=claim.endpoint, topic=claim.credential, message=message
            )
            return
        body = render_webhook(claim, degraded, message_id=message_id, sent_at=datetime.now(UTC))
        await self.sender.send_webhook(url=claim.endpoint, key=claim.credential, body=body)

    @staticmethod
    async def _record(
        repo: DeliveryRepo, outcomes: list[_Outcome], report: DeliveryReport, *, now: datetime
    ) -> None:
        for outcome in outcomes:
            claim = outcome.claim
            if outcome.skipped:
                await repo.release(claim.id, claim.previous_retry_at)
                report.skipped += 1
            elif outcome.message_id is not None:
                await repo.mark_sent(
                    claim.id,
                    [d.id for d in claim.deliveries],
                    message_id=outcome.message_id,
                    now=now,
                )
                report.sent += 1
            else:
                report.failed += 1
                paused = await repo.mark_failed(
                    claim.id,
                    outcome.error or "unknown error",
                    now=now,
                    pause_after=timedelta(seconds=settings.NOTIFICATIONS_PAUSE_AFTER_SECONDS),
                )
                if paused:
                    logger.warning("subscription %s paused after a day failing", claim.id)
                    report.paused += 1


__all__ = ["DeliverNotificationsUseCase", "DeliveryReport"]
