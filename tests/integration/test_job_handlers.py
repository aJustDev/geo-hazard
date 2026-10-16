"""Handlers de job de sincronizacion (ign, aemet, effis) contra PostGIS real.

Cubren el contrato operativo del handler completo (job -> use case -> commit)
y sus dos ramas de fallo de la fuente. En ambas el lote se descarta y el fallo
queda contabilizado en source_sync_state, en su propia sesion, para poder
alertar por rachas (ADR-0019). Una fuente caida (TransientError) NO propaga:
no es fallo del job. Un contrato roto (ProtocolError) si propaga, para que el
job worker lo deje en scheduled_jobs.last_error.
"""

from collections.abc import Iterator

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.aemet.exceptions import AemetProtocolError, AemetTransientError
from app.core.aemet.registry import aemet_client_registry
from app.core.aemet.types import AemetWarning
from app.core.effis.exceptions import EffisProtocolError, EffisTransientError
from app.core.effis.registry import effis_client_registry
from app.core.effis.types import EffisRecord
from app.core.ign.exceptions import IgnProtocolError, IgnTransientError
from app.core.ign.registry import ign_client_registry
from app.core.ign.types import IgnRecord
from app.core.jobs.handlers import aemet_sync as aemet_handler_module
from app.core.jobs.handlers import effis_sync as effis_handler_module
from app.core.jobs.handlers import ign_sync as ign_handler_module
from app.hazards.models.hazard_event import HazardEventORM
from app.hazards.models.sync_state import SourceSyncStateORM

pytestmark = [pytest.mark.integration, pytest.mark.asyncio(loop_scope="session")]


@pytest.fixture
def fresh_registries() -> Iterator[None]:
    ign_client_registry.reset()
    aemet_client_registry.reset()
    effis_client_registry.reset()
    yield
    ign_client_registry.reset()
    aemet_client_registry.reset()
    effis_client_registry.reset()


class _IgnCaida:
    async def fetch_earthquakes(self) -> list[IgnRecord]:
        raise IgnTransientError("apagon simulado")


class _AemetCaida:
    async def fetch_warnings(self) -> list[AemetWarning]:
        raise AemetTransientError("apagon simulado")


class _EffisCaida:
    async def fetch_hotspots(self) -> list[EffisRecord]:
        raise EffisTransientError("apagon simulado")

    async def fetch_burnt_areas(self) -> list[EffisRecord]:
        raise EffisTransientError("apagon simulado")


class _IgnRota:
    async def fetch_earthquakes(self) -> list[IgnRecord]:
        raise IgnProtocolError("contrato roto")


class _AemetRota:
    async def fetch_warnings(self) -> list[AemetWarning]:
        raise AemetProtocolError("contrato roto")


class _EffisRota:
    async def fetch_hotspots(self) -> list[EffisRecord]:
        raise EffisProtocolError("contrato roto")

    async def fetch_burnt_areas(self) -> list[EffisRecord]:
        raise EffisProtocolError("contrato roto")


async def _sync_state(factory: async_sessionmaker, source: str) -> SourceSyncStateORM:
    async with factory() as session:
        return (
            await session.execute(
                select(SourceSyncStateORM).where(SourceSyncStateORM.source == source)
            )
        ).scalar_one()


async def _events_count(factory: async_sessionmaker, source: str) -> int:
    async with factory() as session:
        stmt = (
            select(func.count()).select_from(HazardEventORM).where(HazardEventORM.source == source)
        )
        return (await session.execute(stmt)).scalar_one()


async def test_ign_sync_ingesta_con_el_driver_fake(
    committing_factory: async_sessionmaker,
    monkeypatch: pytest.MonkeyPatch,
    fresh_registries: None,
) -> None:
    # Con IGN_DRIVER=fake (default de tests) el registry construye solo el
    # fake, que sirve 2 sismos conocidos.
    monkeypatch.setattr(ign_handler_module, "async_session_factory", committing_factory)

    await ign_handler_module.ign_sync()

    assert await _events_count(committing_factory, "ign") == 2
    state = await _sync_state(committing_factory, "ign")
    assert state.last_success_at is not None
    assert state.consecutive_failures == 0


async def test_ign_sync_fuente_caida_contabiliza_el_fallo(
    committing_factory: async_sessionmaker,
    monkeypatch: pytest.MonkeyPatch,
    fresh_registries: None,
) -> None:
    monkeypatch.setattr(ign_handler_module, "async_session_factory", committing_factory)
    ign_client_registry.register(_IgnCaida())

    await ign_handler_module.ign_sync()  # no debe propagar

    assert await _events_count(committing_factory, "ign") == 0
    state = await _sync_state(committing_factory, "ign")
    assert state.consecutive_failures == 1
    assert state.last_error is not None
    assert "apagon simulado" in state.last_error


async def test_aemet_sync_ingesta_con_el_driver_fake(
    committing_factory: async_sessionmaker,
    monkeypatch: pytest.MonkeyPatch,
    fresh_registries: None,
) -> None:
    # El fake sirve un aviso naranja (ingerible) y uno verde (se filtra).
    monkeypatch.setattr(aemet_handler_module, "async_session_factory", committing_factory)

    await aemet_handler_module.aemet_sync()

    assert await _events_count(committing_factory, "aemet") == 1
    state = await _sync_state(committing_factory, "aemet")
    assert state.last_success_at is not None
    assert state.consecutive_failures == 0


async def test_aemet_sync_fuente_caida_contabiliza_el_fallo(
    committing_factory: async_sessionmaker,
    monkeypatch: pytest.MonkeyPatch,
    fresh_registries: None,
) -> None:
    monkeypatch.setattr(aemet_handler_module, "async_session_factory", committing_factory)
    aemet_client_registry.register(_AemetCaida())

    await aemet_handler_module.aemet_sync()  # no debe propagar

    assert await _events_count(committing_factory, "aemet") == 0
    state = await _sync_state(committing_factory, "aemet")
    assert state.consecutive_failures == 1
    assert state.last_error is not None
    assert "apagon simulado" in state.last_error


async def test_effis_sync_fuente_caida_contabiliza_el_fallo(
    committing_factory: async_sessionmaker,
    monkeypatch: pytest.MonkeyPatch,
    fresh_registries: None,
) -> None:
    monkeypatch.setattr(effis_handler_module, "async_session_factory", committing_factory)
    effis_client_registry.register(_EffisCaida())

    await effis_handler_module.effis_sync()  # no debe propagar

    assert await _events_count(committing_factory, "effis") == 0
    state = await _sync_state(committing_factory, "effis")
    assert state.consecutive_failures == 1
    assert state.last_error is not None
    assert "apagon simulado" in state.last_error


@pytest.mark.parametrize(
    ("module", "handler", "registry", "client", "exc", "source"),
    [
        pytest.param(
            ign_handler_module,
            "ign_sync",
            ign_client_registry,
            _IgnRota,
            IgnProtocolError,
            "ign",
            id="ign",
        ),
        pytest.param(
            aemet_handler_module,
            "aemet_sync",
            aemet_client_registry,
            _AemetRota,
            AemetProtocolError,
            "aemet",
            id="aemet",
        ),
        pytest.param(
            effis_handler_module,
            "effis_sync",
            effis_client_registry,
            _EffisRota,
            EffisProtocolError,
            "effis",
            id="effis",
        ),
    ],
)
async def test_contrato_roto_contabiliza_el_fallo_y_propaga(
    committing_factory: async_sessionmaker,
    monkeypatch: pytest.MonkeyPatch,
    fresh_registries: None,
    module: object,
    handler: str,
    registry: object,
    client: type,
    exc: type[Exception],
    source: str,
) -> None:
    # Sin esto, un cambio de contrato upstream dejaba consecutive_failures a 0
    # y /sources/status no lo veia hasta que la fuente quedaba stale.
    monkeypatch.setattr(module, "async_session_factory", committing_factory)
    registry.register(client())  # type: ignore[attr-defined]

    with pytest.raises(exc):
        await getattr(module, handler)()

    assert await _events_count(committing_factory, source) == 0
    state = await _sync_state(committing_factory, source)
    assert state.consecutive_failures == 1
    assert state.last_error is not None
    assert "contrato roto" in state.last_error
