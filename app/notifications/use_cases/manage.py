import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.channels.driver import ChannelSender
from app.core.channels.types import NtfyMessage
from app.core.config import settings
from app.core.exceptions.exceptions import BusinessValidationError, NotFoundError
from app.hazards.models import HAZARD_TYPES
from app.notifications.models import SubscriptionORM, WatchAreaORM
from app.notifications.repos.delivery import DeliveryRepo
from app.notifications.repos.subscription import SubscriptionRepo, SubscriptionRow, WeeklyStats
from app.notifications.repos.watch_area import WatchAreaRepo
from app.notifications.schemas.webhook import WebhookArea, WebhookEnvelope
from app.notifications.services.areas import AreaSpec, BboxArea, CircleArea, ProvinceArea
from app.notifications.services.credentials import new_ntfy_topic, new_webhook_key
from app.notifications.services.texts import NOTICE

DEFAULT_NTFY_SERVER = "https://ntfy.sh"


@dataclass(frozen=True, slots=True)
class ChannelSpec:
    """Canal pedido: ntfy (servidor) o webhook (URL), o el de otra
    suscripcion, para compartir topic sin pasarlo por la linea de comandos."""

    kind: str  # "ntfy" | "webhook" | "copy"
    endpoint: str | None = None
    copy_from: uuid.UUID | None = None


@dataclass(frozen=True, slots=True)
class Created:
    subscription_id: uuid.UUID
    area_label: str
    channel: str
    # Solo si se genero ahora: se muestra una vez y no se vuelve a ver.
    new_credential: str | None


@dataclass(slots=True)
class SubscriptionAdmin:
    """Gestion de suscripciones para la CLI (ADR-0021). Como la entrega, es
    duena de sus transacciones: cada orden es una unidad completa."""

    session_factory: async_sessionmaker[AsyncSession]
    sender: ChannelSender

    async def provinces(self) -> list[tuple[str, str]]:
        async with self.session_factory() as session:
            return await WatchAreaRepo(session).provinces()

    async def add(
        self,
        area: AreaSpec,
        *,
        label: str | None,
        hazard_types: list[str],
        severity_min: int,
        channel: ChannelSpec,
    ) -> Created:
        if settings.NOTIFICATIONS_DRIVER == "fake" and settings.ENVIRONMENT != "local":
            # El fake da por enviado todo sin enviar nada.
            raise BusinessValidationError(
                f"NOTIFICATIONS_DRIVER=fake outside local ({settings.ENVIRONMENT}): "
                "set NOTIFICATIONS_DRIVER=http and recreate the container first"
            )
        unknown = set(hazard_types) - set(HAZARD_TYPES)
        if not hazard_types or unknown:
            raise BusinessValidationError(
                f"hazard types must be a non-empty subset of {', '.join(HAZARD_TYPES)}"
            )

        async with self.session_factory() as session:
            subscriptions = SubscriptionRepo(session)
            new_credential: str | None = None
            if channel.kind == "copy":
                if channel.copy_from is None:
                    raise BusinessValidationError("copy needs a subscription id")
                source = await subscriptions.get_by_id(channel.copy_from)
                if source is None:
                    raise NotFoundError("subscription", channel.copy_from)
                kind, endpoint, credential = source.channel, source.endpoint, source.credential
            else:
                kind = channel.kind
                endpoint = channel.endpoint or DEFAULT_NTFY_SERVER
                await self.sender.check_endpoint(endpoint)
                new_credential = new_ntfy_topic() if kind == "ntfy" else new_webhook_key()
                credential = new_credential

            watch_area = await self._create_area(WatchAreaRepo(session), area, label)
            subscription = await subscriptions.create(
                SubscriptionORM(
                    watch_area_id=watch_area.id,
                    hazard_types=hazard_types,
                    severity_min=severity_min,
                    channel=kind,
                    endpoint=endpoint,
                    credential=credential,
                )
            )
            await session.commit()
            return Created(subscription.id, watch_area.label, kind, new_credential)

    @staticmethod
    async def _create_area(repo: WatchAreaRepo, area: AreaSpec, label: str | None) -> WatchAreaORM:
        match area:
            case ProvinceArea():
                return await repo.create_province(area, label=label)
            case BboxArea():
                return await repo.create_bbox(area, label=label)
            case CircleArea():
                return await repo.create_circle(area, label=label)

    async def list_all(self) -> list[SubscriptionRow]:
        async with self.session_factory() as session:
            return await SubscriptionRepo(session).list_with_areas()

    async def pause(self, subscription_id: uuid.UUID) -> None:
        async with self.session_factory() as session:
            subscription = await self._get(session, subscription_id)
            subscription.status = "paused"
            subscription.paused_reason = "pausada a mano"
            # Lo pendiente caduca: un resume no debe mandar avisos rancios.
            await DeliveryRepo(session).fail_pending(subscription_id)
            await session.commit()

    async def resume(self, subscription_id: uuid.UUID) -> None:
        async with self.session_factory() as session:
            subscription = await self._get(session, subscription_id)
            subscription.status = "active"
            subscription.paused_reason = None
            subscription.consecutive_failures = 0
            subscription.failing_since = None
            subscription.retry_at = None
            subscription.last_error = None
            await session.commit()

    async def remove(self, subscription_id: uuid.UUID) -> None:
        async with self.session_factory() as session:
            subscription = await self._get(session, subscription_id)
            await SubscriptionRepo(session).remove(subscription)
            await session.commit()

    async def test(self, subscription_id: uuid.UUID) -> None:
        """Manda un mensaje de prueba ya; lanza ChannelError si no llega."""
        async with self.session_factory() as session:
            subscription = await self._get(session, subscription_id)
            label = await SubscriptionRepo(session).area_label(subscription)
        if subscription.channel == "ntfy":
            await self.sender.send_ntfy(
                server=subscription.endpoint,
                topic=subscription.credential,
                message=NtfyMessage(
                    title=f"geo-hazard: prueba - {label}",
                    body=f"Mensaje de prueba: asi llegaran los avisos de {label}.\n\n{NOTICE}",
                    priority=3,
                    tags=("white_check_mark",),
                ),
            )
            return
        envelope = WebhookEnvelope(
            message_id=uuid.uuid4(),
            subscription_id=subscription.id,
            sent_at=datetime.now(UTC),
            area=WebhookArea(id=subscription.watch_area_id, label=label),
            items=[],
            notice=NOTICE,
            attribution=[],
            degraded_sources=[],
        )
        await self.sender.send_webhook(
            url=subscription.endpoint,
            key=subscription.credential,
            body=envelope.model_dump_json().encode(),
        )

    async def stats(self, *, weeks: int) -> list[WeeklyStats]:
        async with self.session_factory() as session:
            since = datetime.now(UTC) - timedelta(weeks=weeks)
            return await SubscriptionRepo(session).weekly_stats(since)

    @staticmethod
    async def _get(session: AsyncSession, subscription_id: uuid.UUID) -> SubscriptionORM:
        subscription = await SubscriptionRepo(session).get_by_id(subscription_id)
        if subscription is None:
            raise NotFoundError("subscription", subscription_id)
        return subscription


__all__ = ["ChannelSpec", "Created", "SubscriptionAdmin"]
