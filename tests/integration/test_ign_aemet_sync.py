"""Sincronizacion IGN y AEMET contra PostGIS real.

Lo que merece Postgres de verdad aqui es el SQL nuevo de la fase 3: el
cierre de ventanas (close_events) y la regla de reapertura del upsert
(ends_at IS DISTINCT), que los mocks unitarios no pueden demostrar.
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.aemet.drivers.fake import AemetFakeClient
from app.core.aemet.types import MSG_TYPE_ALERT, MSG_TYPE_UPDATE, AemetWarning
from app.core.events.bus import EventBus
from app.core.ign.drivers.fake import IgnFakeClient
from app.hazards.models.hazard_event import HazardEventORM
from app.hazards.repos.hazard_event import HazardEventRepo
from app.hazards.repos.sync_state import SourceSyncStateRepo
from app.hazards.use_cases.sync_aemet import SyncAemetUseCase
from app.hazards.use_cases.sync_ign import SyncIgnUseCase

pytestmark = [pytest.mark.integration, pytest.mark.asyncio(loop_scope="session")]

NOW = datetime.now(UTC).replace(microsecond=0)
SENT_1 = NOW - timedelta(hours=2)
SENT_2 = NOW - timedelta(hours=1)


def _aviso(external_id: str, *, msg_type: str = MSG_TYPE_ALERT, **overrides) -> AemetWarning:
    defaults = dict(
        external_id=external_id,
        msg_type=msg_type,
        sent=SENT_1,
        event="Aviso de temperaturas maximas de nivel naranja",
        phenomenon="AT;Temperaturas maximas",
        level="naranja",
        onset=NOW - timedelta(hours=3),
        expires=NOW + timedelta(hours=6),
        polygon="39.14,-5.58 39.19,-5.61 39.21,-5.56 39.14,-5.58",
        zone="700602",
        area_desc="La Siberia extremena",
    )
    return AemetWarning(**{**defaults, **overrides})


def _aemet_use_case(session: AsyncSession) -> SyncAemetUseCase:
    return SyncAemetUseCase(
        repo=HazardEventRepo(session),
        sync_state=SourceSyncStateRepo(session),
        event_bus=EventBus(session),
    )


async def _row(session: AsyncSession, external_id: str) -> HazardEventORM:
    session.expire_all()  # close_events actualiza por SQL, no via ORM
    stmt = select(HazardEventORM).where(
        HazardEventORM.source == "aemet", HazardEventORM.external_id == external_id
    )
    return (await session.execute(stmt)).scalar_one()


async def test_sync_ign_ingesta_y_es_idempotente(db_session: AsyncSession) -> None:
    use_case = SyncIgnUseCase(
        repo=HazardEventRepo(db_session),
        sync_state=SourceSyncStateRepo(db_session),
        event_bus=EventBus(db_session),
    )

    assert await use_case.execute(client=IgnFakeClient()) == (2, 0)
    # Re-servido identico: no-op total (ADR-0008).
    assert await use_case.execute(client=IgnFakeClient()) == (0, 0)

    state = await SourceSyncStateRepo(db_session).get("ign")
    assert state is not None
    assert state.cursor == {"last_event_at": "2026-07-02T05:06:37+00:00"}


async def test_ciclo_de_vida_de_un_aviso_aemet(db_session: AsyncSession) -> None:
    use_case = _aemet_use_case(db_session)

    # Boletin 1: nace el aviso X.
    assert await use_case.execute(client=AemetFakeClient(warnings=[_aviso("aviso-x")])) == (
        1,
        0,
        0,
    )
    x = await _row(db_session, "aviso-x")
    assert x.ends_at == NOW + timedelta(hours=6)  # su expires original

    # Boletin 2: Y supersede a X (X ya no viene). El cierre por referencia
    # gana al cierre por desaparicion: ends_at = sent del Update, no "ahora".
    update_y = _aviso("aviso-y", msg_type=MSG_TYPE_UPDATE, sent=SENT_2, references=("aviso-x",))
    inserted, updated, closed = await use_case.execute(client=AemetFakeClient(warnings=[update_y]))
    assert (inserted, updated, closed) == (1, 0, 1)
    assert (await _row(db_session, "aviso-x")).ends_at == SENT_2

    # Boletin 3: vacio. Y desaparece sin Cancel: se cierra a "ahora".
    inserted, updated, closed = await use_case.execute(client=AemetFakeClient(warnings=[]))
    assert (inserted, updated, closed) == (0, 0, 1)
    y = await _row(db_session, "aviso-y")
    assert y.ends_at is not None
    assert y.ends_at < NOW + timedelta(hours=6)

    # Boletin 4: Y reaparece abierto con contenido identico. La fuente manda:
    # la regla ends_at IS DISTINCT del upsert reabre la fila (ADR-0010).
    reissued_y = _aviso("aviso-y", msg_type=MSG_TYPE_UPDATE, sent=SENT_2, references=("aviso-x",))
    inserted, updated, closed = await use_case.execute(
        client=AemetFakeClient(warnings=[reissued_y])
    )
    assert (inserted, updated) == (0, 1)
    assert (await _row(db_session, "aviso-y")).ends_at == NOW + timedelta(hours=6)


async def test_el_cierre_no_reabre_avisos_ya_expirados(db_session: AsyncSession) -> None:
    # Un aviso cuya ventana ya paso conserva su expires aunque llegue un
    # cierre posterior: close_events solo toca filas aun abiertas.
    expired = _aviso("aviso-viejo", expires=NOW - timedelta(hours=1))
    use_case = _aemet_use_case(db_session)
    await use_case.execute(client=AemetFakeClient(warnings=[expired]))

    closed = await HazardEventRepo(db_session).close_events(
        source="aemet", external_ids=["aviso-viejo"], ended_at=NOW
    )

    assert closed == 0
    assert (await _row(db_session, "aviso-viejo")).ends_at == NOW - timedelta(hours=1)
