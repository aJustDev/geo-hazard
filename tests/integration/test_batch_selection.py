"""Invariante de ADR-0021: las filas que escribio un lote son exactamente las
que llevan su batch_at en created_at (inserts) o updated_at (updates y
cierres). Cada sync corre en su propia transaccion, como en el job real."""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.aemet.drivers.fake import AemetFakeClient
from app.core.aemet.types import MSG_TYPE_ALERT, MSG_TYPE_UPDATE, AemetWarning
from app.core.effis.drivers.fake import EffisFakeClient
from app.core.effis.types import KIND_BURNT_AREA, KIND_HOTSPOT, EffisRecord
from app.core.events.bus import EventBus
from app.core.events.models import OutboxEventORM
from app.core.ign.drivers.fake import IgnFakeClient
from app.core.ign.types import IgnRecord
from app.hazards.models.hazard_event import HazardEventORM
from app.hazards.repos.hazard_event import HazardEventRepo
from app.hazards.repos.sync_state import SourceSyncStateRepo
from app.hazards.use_cases.sync_aemet import SyncAemetUseCase
from app.hazards.use_cases.sync_effis import SyncEffisUseCase
from app.hazards.use_cases.sync_ign import SyncIgnUseCase

pytestmark = [pytest.mark.integration, pytest.mark.asyncio(loop_scope="session")]

NOW = datetime.now(UTC).replace(microsecond=0)


async def _sync(factory: async_sessionmaker, use_case_cls: Any, client: Any) -> datetime:
    """Un lote en su transaccion; devuelve el batch_at publicado."""
    async with factory() as session:
        use_case = use_case_cls(
            repo=HazardEventRepo(session),
            sync_state=SourceSyncStateRepo(session),
            event_bus=EventBus(session),
        )
        await use_case.execute(client=client)
        await session.commit()
    async with factory() as session:
        event = (
            await session.execute(
                select(OutboxEventORM).order_by(OutboxEventORM.created_at.desc()).limit(1)
            )
        ).scalar_one()
    # Round-trip por JSONB: la marca vuelve al microsegundo.
    return datetime.fromisoformat(event.payload["batch_at"])


async def _selected(factory: async_sessionmaker, source: str, batch_at: datetime) -> set[str]:
    async with factory() as session:
        rows = await session.execute(
            select(HazardEventORM.external_id).where(
                HazardEventORM.source == source,
                or_(HazardEventORM.created_at == batch_at, HazardEventORM.updated_at == batch_at),
            )
        )
        return set(rows.scalars().all())


async def _ends_at(factory: async_sessionmaker, source: str) -> dict[str, datetime | None]:
    async with factory() as session:
        rows = await session.execute(
            select(HazardEventORM.external_id, HazardEventORM.ends_at).where(
                HazardEventORM.source == source
            )
        )
        return {external_id: ends_at for external_id, ends_at in rows}


def _quake(external_id: str, magnitude: float) -> IgnRecord:
    return IgnRecord(
        external_id=external_id,
        magnitude=magnitude,
        region="MURCIA",
        latitude=37.9,
        longitude=-1.1,
        occurred_at=NOW - timedelta(hours=1),
    )


async def test_lotes_ign(committing_factory: async_sessionmaker) -> None:
    t1 = await _sync(
        committing_factory,
        SyncIgnUseCase,
        IgnFakeClient(earthquakes=[_quake("eq-1", 2.5), _quake("eq-2", 3.1)]),
    )
    assert await _selected(committing_factory, "ign", t1) == {"eq-1", "eq-2"}

    # Revision de eq-1, eq-2 re-servido identico y eq-3 nuevo.
    t2 = await _sync(
        committing_factory,
        SyncIgnUseCase,
        IgnFakeClient(earthquakes=[_quake("eq-1", 3.4), _quake("eq-2", 3.1), _quake("eq-3", 2.0)]),
    )
    assert t2 > t1
    assert await _selected(committing_factory, "ign", t2) == {"eq-1", "eq-3"}
    # Un lote viejo sigue alcanzando por created_at lo que inserto aunque un
    # lote posterior lo haya reescrito: un reintento tardio del handler ve la
    # fila con su estado actual, y el matching es idempotente (ADR-0021).
    assert await _selected(committing_factory, "ign", t1) == {"eq-1", "eq-2"}


def _warning(external_id: str, *, msg_type: str = MSG_TYPE_ALERT, **kw: Any) -> AemetWarning:
    defaults: dict[str, Any] = dict(
        sent=NOW - timedelta(minutes=20),
        event="Aviso de tormentas de nivel amarillo",
        phenomenon="TO;Tormentas",
        level="amarillo",
        onset=NOW - timedelta(hours=1),
        expires=NOW + timedelta(hours=6),
        polygon="37.9,-1.2 38.0,-1.2 38.0,-1.0 37.9,-1.2",
        zone="613001",
        area_desc="Vega del Segura",
    )
    return AemetWarning(external_id=external_id, msg_type=msg_type, **{**defaults, **kw})


async def test_lotes_aemet_update_y_retirado(committing_factory: async_sessionmaker) -> None:
    t1 = await _sync(
        committing_factory,
        SyncAemetUseCase,
        AemetFakeClient(warnings=[_warning("w-a"), _warning("w-b", zone="613002")]),
    )
    assert await _selected(committing_factory, "aemet", t1) == {"w-a", "w-b"}

    # Boletin nuevo: un Update sustituye a w-a con otro identificador y w-b
    # desaparece sin Cancel.
    update = _warning(
        "w-a2", msg_type=MSG_TYPE_UPDATE, references=("w-a",), sent=NOW - timedelta(minutes=5)
    )
    t2 = await _sync(committing_factory, SyncAemetUseCase, AemetFakeClient(warnings=[update]))

    assert await _selected(committing_factory, "aemet", t2) == {"w-a", "w-a2", "w-b"}
    ends = await _ends_at(committing_factory, "aemet")
    # Lo cerrado por el lote queda cerrado a su marca o antes: ni el
    # supersedido ni el retirado parecen vivos (ADR-0021, B1).
    assert ends["w-a"] is not None and ends["w-a"] <= t2
    assert ends["w-b"] == t2
    assert ends["w-a2"] is not None and ends["w-a2"] > t2


def _hotspot(external_id: str) -> EffisRecord:
    return EffisRecord(
        external_id=external_id,
        kind=KIND_HOTSPOT,
        geometry={"type": "Point", "coordinates": [-1.5, 38.0]},
        observed_at=NOW - timedelta(hours=2),
    )


def _burnt(external_id: str) -> EffisRecord:
    return EffisRecord(
        external_id=external_id,
        kind=KIND_BURNT_AREA,
        geometry={
            "type": "Polygon",
            "coordinates": [[[-1.6, 38.0], [-1.5, 38.0], [-1.5, 38.1], [-1.6, 38.1], [-1.6, 38.0]]],
        },
        observed_at=NOW - timedelta(days=1),
        area_ha=600.0,
    )


async def test_lotes_effis_con_cierre(committing_factory: async_sessionmaker) -> None:
    t1 = await _sync(
        committing_factory,
        SyncEffisUseCase,
        EffisFakeClient(hotspots=[_hotspot("hs-1")], burnt_areas=[_burnt("ba-1")]),
    )
    assert await _selected(committing_factory, "effis", t1) == {"hs-1", "ba-1"}

    # ba-1 deja de servirse y llega un hotspot nuevo; hs-1 se re-sirve igual.
    t2 = await _sync(
        committing_factory,
        SyncEffisUseCase,
        EffisFakeClient(hotspots=[_hotspot("hs-1"), _hotspot("hs-2")], burnt_areas=[]),
    )
    assert await _selected(committing_factory, "effis", t2) == {"ba-1", "hs-2"}
    assert (await _ends_at(committing_factory, "effis"))["ba-1"] == t2
