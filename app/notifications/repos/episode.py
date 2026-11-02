import uuid
from collections.abc import Iterable
from datetime import datetime
from typing import Any

from sqlalchemy import func, select, tuple_, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.notifications.models import NotificationDeliveryORM, NotificationEpisodeORM
from app.notifications.services.episodes import OpenEpisode


class EpisodeRepo:
    """Episodios y entregas que produce el cruce de un lote. No commitea."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def open_episodes(
        self, keys: Iterable[tuple[uuid.UUID, str]]
    ) -> dict[tuple[uuid.UUID, str], OpenEpisode]:
        wanted = list(keys)
        if not wanted:
            return {}
        episode = NotificationEpisodeORM
        rows = await self.session.execute(
            select(
                episode.subscription_id,
                episode.key,
                episode.id,
                episode.notified_severity,
                episode.expires_at,
            )
            .where(
                episode.closed_at.is_(None),
                tuple_(episode.subscription_id, episode.key).in_(wanted),
            )
            .with_for_update()
        )
        return {
            (sub_id, key): OpenEpisode(id=ep_id, notified_severity=notified, expires_at=expires)
            for sub_id, key, ep_id, notified, expires in rows
        }

    async def close(self, episode_id: uuid.UUID, *, at: datetime) -> None:
        await self.session.execute(
            update(NotificationEpisodeORM)
            .where(
                NotificationEpisodeORM.id == episode_id, NotificationEpisodeORM.closed_at.is_(None)
            )
            .values(closed_at=at)
        )

    async def open(
        self,
        *,
        subscription_id: uuid.UUID,
        key: str,
        severity: int,
        expires_at: datetime | None,
        at: datetime,
    ) -> uuid.UUID:
        episode = NotificationEpisodeORM
        new_id: uuid.UUID | None = await self.session.scalar(
            pg_insert(episode)
            .values(
                subscription_id=subscription_id,
                key=key,
                notified_severity=severity,
                expires_at=expires_at,
                opened_at=at,
                last_matched_at=at,
            )
            .on_conflict_do_nothing(
                index_elements=["subscription_id", "key"],
                index_where=episode.closed_at.is_(None),
            )
            .returning(episode.id)
        )
        if new_id is None:
            # Otro proceso abrio el mismo episodio entre el SELECT FOR UPDATE
            # y este INSERT: que el outbox reintente el lote entero.
            raise RuntimeError(f"episode {key!r} opened concurrently")
        return new_id

    async def refresh(
        self,
        episode_id: uuid.UUID,
        *,
        notified_severity: int,
        expires_at: datetime | None,
        at: datetime,
    ) -> None:
        episode = NotificationEpisodeORM
        values: dict[str, Any] = {
            "notified_severity": func.greatest(episode.notified_severity, notified_severity),
            "last_matched_at": func.greatest(episode.last_matched_at, at),
        }
        if expires_at is not None:  # IGN y EFFIS no caducan
            values["expires_at"] = func.greatest(episode.expires_at, expires_at)
        await self.session.execute(update(episode).where(episode.id == episode_id).values(**values))

    async def add_delivery(
        self,
        *,
        subscription_id: uuid.UUID,
        episode_id: uuid.UUID,
        severity: int,
        reason: str,
        items: list[dict[str, Any]],
        item_count: int,
    ) -> bool:
        """Idempotente por (episodio, severidad): un reintento no duplica."""
        created = await self.session.scalar(
            pg_insert(NotificationDeliveryORM)
            .values(
                subscription_id=subscription_id,
                episode_id=episode_id,
                severity=severity,
                reason=reason,
                items=items,
                item_count=item_count,
            )
            .on_conflict_do_nothing(index_elements=["episode_id", "severity"])
            .returning(NotificationDeliveryORM.id)
        )
        return created is not None


__all__ = ["EpisodeRepo"]
