"""Cruce de un lote con las suscripciones activas (ADR-0021)."""

import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import ColumnElement, and_, any_, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.hazards.models import HazardEventORM, in_province
from app.notifications.models import SubscriptionORM, WatchAreaORM


@dataclass(frozen=True, slots=True)
class Match:
    subscription_id: uuid.UUID
    event_id: uuid.UUID
    source: str
    hazard_type: str
    external_id: str
    severity: int
    starts_at: datetime
    ends_at: datetime | None
    attrs: dict[str, Any]
    geometry: dict[str, Any]


def _notifiable(source: str, batch_at: datetime, quake_max_age: timedelta) -> ColumnElement[bool]:
    """Filas del lote que pueden avisar. AEMET: lo que no ha terminado (fuera
    los cierres, dentro los avisos de manana). EFFIS: areas quemadas abiertas
    (los hotspots nunca avisan). IGN: sismos recientes, para que una revision
    de la ventana de 10 dias no dispare una rafaga."""
    event = HazardEventORM
    if source == "aemet":
        return event.ends_at > batch_at
    if source == "effis":
        return and_(event.attrs["kind"].astext == "burnt_area", event.ends_at.is_(None))
    return event.starts_at >= batch_at - quake_max_age


def _area_contains(event: type[HazardEventORM], area: type[WatchAreaORM]) -> ColumnElement[bool]:
    """bbox y circulo: el evento la toca. Provincia: la regla comun de
    `in_province` (un punto cae dentro; un poligono es suyo si es la provincia
    con la que mas solapa, porque las zonas AEMET cruzan limites; ADR-0021)."""
    return and_(
        func.ST_Intersects(area.geom, event.geom),
        or_(area.kind != "province", in_province(event.geom, area.params["code"].astext)),
    )


class MatchingRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def has_active_subscriptions(self) -> bool:
        found = await self.session.scalar(
            select(exists().where(SubscriptionORM.status == "active"))
        )
        return bool(found)

    async def matches(
        self, *, source: str, batch_at: datetime, quake_max_age: timedelta
    ) -> list[Match]:
        event, subscription, area = HazardEventORM, SubscriptionORM, WatchAreaORM
        rows = await self.session.execute(
            select(
                subscription.id,
                event.id,
                event.source,
                event.hazard_type,
                event.external_id,
                event.severity,
                event.starts_at,
                event.ends_at,
                event.attrs,
                func.ST_AsGeoJSON(event.geom, 6),
            )
            .join(
                subscription,
                and_(
                    subscription.status == "active",
                    event.hazard_type == any_(subscription.hazard_types),
                    event.severity >= subscription.severity_min,
                ),
            )
            .join(area, area.id == subscription.watch_area_id)
            .where(
                event.source == source,
                or_(event.created_at == batch_at, event.updated_at == batch_at),
                _notifiable(source, batch_at, quake_max_age),
                _area_contains(event, area),
            )
            .order_by(subscription.id, event.severity.desc(), event.starts_at)
        )
        return [
            Match(
                subscription_id=sub_id,
                event_id=event_id,
                source=src,
                hazard_type=hazard_type,
                external_id=external_id,
                severity=severity,
                starts_at=starts_at,
                ends_at=ends_at,
                attrs=attrs,
                geometry=json.loads(geojson),
            )
            for (
                sub_id,
                event_id,
                src,
                hazard_type,
                external_id,
                severity,
                starts_at,
                ends_at,
                attrs,
                geojson,
            ) in rows
        ]


__all__ = ["Match", "MatchingRepo"]
