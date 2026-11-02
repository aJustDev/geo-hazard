import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.notifications.repos.episode import EpisodeRepo
from app.notifications.repos.matching import Match, MatchingRepo
from app.notifications.services.episodes import Action, decide, episode_key

# Foto de eventos por entrega; item_count guarda el total.
_MAX_ITEMS_PER_DELIVERY = 20


@dataclass(slots=True)
class _Group:
    severity: int = 0
    expires_at: datetime | None = None
    matches: list[Match] = field(default_factory=list)


def _feature(match: Match) -> dict[str, Any]:
    return {
        "type": "Feature",
        "id": str(match.event_id),
        "geometry": match.geometry,
        "properties": {
            "source": match.source,
            "hazard_type": match.hazard_type,
            "severity": match.severity,
            "starts_at": match.starts_at.isoformat(),
            "ends_at": match.ends_at.isoformat() if match.ends_at else None,
            "external_id": match.external_id,
            "attrs": match.attrs,
        },
    }


@dataclass(slots=True)
class MatchBatchUseCase:
    """Cruza un lote con las suscripciones y decide episodios y entregas
    (ADR-0021). Solo BD, idempotente: reejecutar el mismo lote no duplica.
    No commitea: la transaccion es del handler del outbox."""

    session: AsyncSession

    async def execute(self, *, source: str, batch_at: datetime) -> int:
        matching = MatchingRepo(self.session)
        if not await matching.has_active_subscriptions():
            return 0
        matches = await matching.matches(
            source=source,
            batch_at=batch_at,
            quake_max_age=timedelta(seconds=settings.NOTIFICATIONS_QUAKE_MAX_AGE_SECONDS),
        )

        groups: dict[tuple[uuid.UUID, str], _Group] = {}
        for match in matches:
            key = episode_key(source=match.source, external_id=match.external_id, attrs=match.attrs)
            group = groups.setdefault((match.subscription_id, key), _Group())
            group.severity = max(group.severity, match.severity)
            group.matches.append(match)
            if match.source == "aemet" and match.ends_at is not None:
                group.expires_at = max(group.expires_at or match.ends_at, match.ends_at)

        episodes = EpisodeRepo(self.session)
        open_episodes = await episodes.open_episodes(groups)
        grace = timedelta(seconds=settings.NOTIFICATIONS_AEMET_EPISODE_GRACE_SECONDS)
        created = 0
        for (subscription_id, key), group in groups.items():
            current = open_episodes.get((subscription_id, key))
            action = decide(current, severity=group.severity, batch_at=batch_at, grace=grace)
            if action is Action.TOUCH and current is not None:
                await episodes.refresh(
                    current.id,
                    notified_severity=current.notified_severity,
                    expires_at=group.expires_at,
                    at=batch_at,
                )
                continue
            if action is Action.ESCALATE and current is not None:
                episode_id = current.id
                await episodes.refresh(
                    episode_id,
                    notified_severity=group.severity,
                    expires_at=group.expires_at,
                    at=batch_at,
                )
            else:
                if current is not None:
                    await episodes.close(current.id, at=batch_at)
                episode_id = await episodes.open(
                    subscription_id=subscription_id,
                    key=key,
                    severity=group.severity,
                    expires_at=group.expires_at,
                    at=batch_at,
                )
            created += await episodes.add_delivery(
                subscription_id=subscription_id,
                episode_id=episode_id,
                severity=group.severity,
                reason="escalated" if action is Action.ESCALATE else "opened",
                items=[_feature(m) for m in group.matches[:_MAX_ITEMS_PER_DELIVERY]],
                item_count=len(group.matches),
            )
        return created


__all__ = ["MatchBatchUseCase"]
