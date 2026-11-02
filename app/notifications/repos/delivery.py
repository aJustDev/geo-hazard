"""Persistencia del job de entrega (ADR-0021). No commitea: las fronteras
de transaccion son del caso de uso."""

import uuid
from datetime import datetime, timedelta

from sqlalchemy import delete, exists, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.notifications.models import (
    NotificationDeliveryORM,
    NotificationEpisodeORM,
    SubscriptionORM,
    WatchAreaORM,
)
from app.notifications.schemas.delivery import ClaimedSubscription, PendingDelivery

_BACKOFF_BASE_SECONDS = 60
_BACKOFF_CAP_SECONDS = 3600


def backoff(consecutive_failures: int) -> timedelta:
    """60 s, 2 min, 4 min... con techo de 1 h."""
    return timedelta(
        seconds=min(_BACKOFF_BASE_SECONDS * 2**consecutive_failures, _BACKOFF_CAP_SECONDS)
    )


class DeliveryRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def db_now(self) -> datetime:
        now: datetime = (await self.session.execute(select(func.now()))).scalar_one()
        return now

    async def claim(
        self, now: datetime, *, min_interval: timedelta, limit: int
    ) -> list[ClaimedSubscription]:
        """Reclama suscripciones activas con entregas pendientes y fuera de
        backoff y de intervalo minimo. retry_at se adelanta ya al backoff
        siguiente: hace de lease (otro worker no la toma) y, si el envio
        falla o el proceso muere a medias, es el reintento."""
        subscription = SubscriptionORM
        pending = exists().where(
            NotificationDeliveryORM.subscription_id == subscription.id,
            NotificationDeliveryORM.status == "pending",
        )
        claimed = (
            (
                await self.session.execute(
                    select(subscription)
                    .where(
                        subscription.status == "active",
                        or_(subscription.retry_at.is_(None), subscription.retry_at <= now),
                        or_(
                            subscription.last_sent_at.is_(None),
                            subscription.last_sent_at <= now - min_interval,
                        ),
                        pending,
                    )
                    .order_by(subscription.last_sent_at.asc().nulls_first())
                    .limit(limit)
                    .with_for_update(skip_locked=True)
                )
            )
            .scalars()
            .all()
        )
        if not claimed:
            return []

        previous = {s.id: s.retry_at for s in claimed}
        for s in claimed:
            s.retry_at = now + backoff(s.consecutive_failures)

        ids = [s.id for s in claimed]
        labels = dict(
            (
                await self.session.execute(
                    select(WatchAreaORM.id, WatchAreaORM.label).where(
                        WatchAreaORM.id.in_({s.watch_area_id for s in claimed})
                    )
                )
            ).all()
        )
        rows = (
            (
                await self.session.execute(
                    select(NotificationDeliveryORM)
                    .where(
                        NotificationDeliveryORM.subscription_id.in_(ids),
                        NotificationDeliveryORM.status == "pending",
                    )
                    .order_by(
                        NotificationDeliveryORM.severity.desc(),
                        NotificationDeliveryORM.created_at,
                    )
                )
            )
            .scalars()
            .all()
        )
        for row in rows:
            row.attempts += 1
        await self.session.flush()

        by_subscription: dict[uuid.UUID, list[PendingDelivery]] = {}
        for row in rows:
            by_subscription.setdefault(row.subscription_id, []).append(
                PendingDelivery(
                    id=row.id,
                    episode_id=row.episode_id,
                    reason=row.reason,
                    severity=row.severity,
                    items=row.items,
                    item_count=row.item_count,
                )
            )
        return [
            ClaimedSubscription(
                id=s.id,
                channel=s.channel,
                endpoint=s.endpoint,
                credential=s.credential,
                hazard_types=list(s.hazard_types),
                area_id=s.watch_area_id,
                area_label=labels[s.watch_area_id],
                previous_retry_at=previous[s.id],
                deliveries=by_subscription[s.id],
            )
            for s in claimed
        ]

    async def mark_sent(
        self,
        subscription_id: uuid.UUID,
        delivery_ids: list[uuid.UUID],
        *,
        message_id: uuid.UUID,
        now: datetime,
    ) -> None:
        await self.session.execute(
            update(NotificationDeliveryORM)
            .where(NotificationDeliveryORM.id.in_(delivery_ids))
            .values(status="sent", sent_at=now, message_id=message_id)
        )
        await self.session.execute(
            update(SubscriptionORM)
            .where(SubscriptionORM.id == subscription_id)
            .values(
                last_sent_at=now,
                consecutive_failures=0,
                failing_since=None,
                retry_at=None,
                last_error=None,
            )
        )

    async def mark_failed(
        self, subscription_id: uuid.UUID, error: str, *, now: datetime, pause_after: timedelta
    ) -> bool:
        """Cuenta el fallo; tras `pause_after` fallando sin interrupcion pausa
        la suscripcion y da por fallidas sus pendientes, para que un resume
        no mande avisos rancios. Devuelve si la pauso."""
        subscription = await self.session.get(SubscriptionORM, subscription_id)
        if subscription is None:
            return False
        subscription.consecutive_failures += 1
        subscription.failing_since = subscription.failing_since or now
        subscription.last_error = error[:500]
        if subscription.failing_since > now - pause_after:
            return False
        subscription.status = "paused"
        subscription.paused_reason = (
            f"entregas fallidas desde {subscription.failing_since:%Y-%m-%d %H:%M} UTC: {error}"
        )[:500]
        await self.fail_pending(subscription_id)
        return True

    async def fail_pending(self, subscription_id: uuid.UUID) -> None:
        await self.session.execute(
            update(NotificationDeliveryORM)
            .where(
                NotificationDeliveryORM.subscription_id == subscription_id,
                NotificationDeliveryORM.status == "pending",
            )
            .values(status="failed")
        )

    async def release(self, subscription_id: uuid.UUID, retry_at: datetime | None) -> None:
        """Devuelve el lease de una suscripcion reclamada que no se llego a
        intentar (presupuesto agotado)."""
        await self.session.execute(
            update(SubscriptionORM)
            .where(SubscriptionORM.id == subscription_id)
            .values(retry_at=retry_at)
        )

    async def purge(self, now: datetime, *, retention: timedelta) -> tuple[int, int]:
        cutoff = now - retention
        deliveries = await self.session.execute(
            delete(NotificationDeliveryORM)
            .where(
                NotificationDeliveryORM.status.in_(("sent", "failed")),
                func.coalesce(NotificationDeliveryORM.sent_at, NotificationDeliveryORM.created_at)
                < cutoff,
            )
            .returning(NotificationDeliveryORM.id)
        )
        # IGN y EFFIS nunca cierran episodios: cuenta su ultimo casado.
        episode = NotificationEpisodeORM
        episodes = await self.session.execute(
            delete(episode)
            .where(
                func.coalesce(episode.closed_at, episode.last_matched_at) < cutoff,
                or_(episode.expires_at.is_(None), episode.expires_at < cutoff),
                ~exists().where(
                    NotificationDeliveryORM.episode_id == episode.id,
                    NotificationDeliveryORM.status == "pending",
                ),
            )
            .returning(episode.id)
        )
        return len(deliveries.all()), len(episodes.all())


__all__ = ["DeliveryRepo", "backoff"]
