import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import delete, distinct, exists, func, select

from app.core.repo import BaseRepo
from app.notifications.models import NotificationDeliveryORM, SubscriptionORM, WatchAreaORM


@dataclass(frozen=True, slots=True)
class SubscriptionRow:
    subscription: SubscriptionORM
    area_label: str
    pending: int


@dataclass(frozen=True, slots=True)
class WeeklyStats:
    subscription_id: uuid.UUID
    area_label: str
    week: datetime
    messages: int
    deliveries: int


class SubscriptionRepo(BaseRepo[SubscriptionORM]):
    model = SubscriptionORM

    async def list_with_areas(self) -> list[SubscriptionRow]:
        pending = (
            select(func.count())
            .where(
                NotificationDeliveryORM.subscription_id == SubscriptionORM.id,
                NotificationDeliveryORM.status == "pending",
            )
            .scalar_subquery()
        )
        rows = await self.session.execute(
            select(SubscriptionORM, WatchAreaORM.label, pending)
            .join(WatchAreaORM, WatchAreaORM.id == SubscriptionORM.watch_area_id)
            .order_by(SubscriptionORM.created_at)
        )
        return [SubscriptionRow(sub, label, count) for sub, label, count in rows]

    async def area_label(self, subscription: SubscriptionORM) -> str:
        label: str = (
            await self.session.execute(
                select(WatchAreaORM.label).where(WatchAreaORM.id == subscription.watch_area_id)
            )
        ).scalar_one()
        return label

    async def remove(self, subscription: SubscriptionORM) -> None:
        """Borra la suscripcion (episodios y entregas en cascada) y su area si
        ya no la usa nadie."""
        area_id = subscription.watch_area_id
        await self.delete(subscription)
        in_use = await self.session.scalar(
            select(exists().where(SubscriptionORM.watch_area_id == area_id))
        )
        if not in_use:
            await self.session.execute(delete(WatchAreaORM).where(WatchAreaORM.id == area_id))

    async def weekly_stats(self, since: datetime) -> list[WeeklyStats]:
        week = func.date_trunc("week", NotificationDeliveryORM.sent_at).label("week")
        rows = await self.session.execute(
            select(
                SubscriptionORM.id,
                WatchAreaORM.label,
                week,
                func.count(distinct(NotificationDeliveryORM.message_id)),
                func.count(),
            )
            .join(SubscriptionORM, SubscriptionORM.id == NotificationDeliveryORM.subscription_id)
            .join(WatchAreaORM, WatchAreaORM.id == SubscriptionORM.watch_area_id)
            .where(
                NotificationDeliveryORM.status == "sent", NotificationDeliveryORM.sent_at >= since
            )
            .group_by(SubscriptionORM.id, WatchAreaORM.label, week)
            .order_by(SubscriptionORM.id, week)
        )
        return [WeeklyStats(*row) for row in rows]


__all__ = ["SubscriptionRepo", "SubscriptionRow", "WeeklyStats"]
