"""Pipeline EFFIS end-to-end contra PostGIS real: job -> upsert -> outbox ->
snapshot GeoParquet. Es el contrato vertebral de la fase 2."""

from pathlib import Path

import duckdb
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core import config
from app.core.db import async_session_factory as _real_factory  # noqa: F401
from app.core.effis.registry import effis_client_registry
from app.core.events import worker as events_worker_module
from app.core.events.models import OutboxEventORM
from app.core.events.worker import OutboxWorker
from app.core.jobs.handlers import effis_sync as effis_sync_module
from app.hazards.event_handlers import export_geoparquet as export_module
from app.hazards.models.hazard_event import HazardEventORM
from app.hazards.models.sync_state import SourceSyncStateORM

pytestmark = [pytest.mark.integration, pytest.mark.asyncio(loop_scope="session")]


@pytest.fixture
def wired_pipeline(
    committing_factory: async_sessionmaker,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> Path:
    """Cablea el pipeline entero contra el Postgres efimero y un DATA_DIR tmp."""
    monkeypatch.setattr(effis_sync_module, "async_session_factory", committing_factory)
    monkeypatch.setattr(events_worker_module, "async_session_factory", committing_factory)
    monkeypatch.setattr(export_module, "async_session_factory", committing_factory)
    monkeypatch.setattr(config.settings, "DATA_DIR", str(tmp_path))
    (tmp_path / "exports").mkdir()
    effis_client_registry.reset()
    return tmp_path


async def _count(factory: async_sessionmaker, model: type) -> int:
    async with factory() as session:
        return (await session.execute(select(func.count()).select_from(model))).scalar_one()


async def test_pipeline_completo_effis(
    committing_factory: async_sessionmaker, wired_pipeline: Path
) -> None:
    # 1. El job ingiere (driver fake: 1 hotspot + 1 area quemada) y commitea.
    await effis_sync_module.effis_sync()

    assert await _count(committing_factory, HazardEventORM) == 2
    async with committing_factory() as session:
        state = await session.get(SourceSyncStateORM, "effis")
        assert state is not None
        assert state.consecutive_failures == 0
        event = (
            await session.execute(
                select(OutboxEventORM).where(OutboxEventORM.event_type == "hazards.batch_ingested")
            )
        ).scalar_one()
        assert event.payload == {"source": "effis", "inserted": 2, "updated": 0}

    # 2. El worker del outbox despacha el evento -> snapshot GeoParquet.
    await OutboxWorker()._process_batch()

    async with committing_factory() as session:
        event = (
            await session.execute(
                select(OutboxEventORM).where(OutboxEventORM.event_type == "hazards.batch_ingested")
            )
        ).scalar_one()
        assert event.status == "PROCESSED"

    snapshot = wired_pipeline / "exports" / "hazard_events_effis.parquet"
    assert snapshot.exists()
    con = duckdb.connect()
    con.execute("INSTALL spatial; LOAD spatial")
    count, geom_type = con.execute(
        "SELECT count(*), min(ST_GeometryType(geom)) FROM read_parquet(?)", [str(snapshot)]
    ).fetchone()
    con.close()
    assert count == 2
    assert geom_type in {"POINT", "POLYGON"}

    # 3. Segundo sync identico: el content_hash lo convierte en no-op total
    #    (ni filas nuevas ni evento de lote nuevo).
    await effis_sync_module.effis_sync()

    assert await _count(committing_factory, HazardEventORM) == 2
    assert await _count(committing_factory, OutboxEventORM) == 1
