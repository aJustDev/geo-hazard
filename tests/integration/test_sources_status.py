"""Contrato HTTP de /v1/sources/status contra PostGIS real: frescura por
cadencia propia de cada fuente, fuentes stale, con fallos y nunca-ejecutadas."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.db import get_session
from app.core.jobs.models import ScheduledJobORM
from app.hazards.models.sync_state import SourceSyncStateORM
from app.main import app

pytestmark = [pytest.mark.integration, pytest.mark.asyncio(loop_scope="session")]


def _client(factory: async_sessionmaker) -> httpx.AsyncClient:
    async def _override() -> AsyncIterator[AsyncSession]:
        async with factory() as session:
            yield session

    app.dependency_overrides[get_session] = _override
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


def _by_source(body: dict) -> dict[str, dict]:
    return {s["source"]: s for s in body["sources"]}


async def test_status_mezcla_degraded(committing_factory: async_sessionmaker) -> None:
    now = datetime.now(UTC)
    async with committing_factory() as session:
        session.add_all(
            [
                # effis sano: sincroniza cada 4h, ultimo exito hace 30 min.
                ScheduledJobORM(job_name="effis_sync", interval_seconds=14400),
                SourceSyncStateORM(
                    source="effis",
                    last_run_at=now - timedelta(minutes=30),
                    last_success_at=now - timedelta(minutes=30),
                    consecutive_failures=0,
                ),
                # ign stale: cadencia 15 min, sin exito desde hace 2h (> 3*900).
                ScheduledJobORM(job_name="ign_sync", interval_seconds=900),
                SourceSyncStateORM(
                    source="ign",
                    last_run_at=now - timedelta(hours=2),
                    last_success_at=now - timedelta(hours=2),
                    consecutive_failures=0,
                ),
                # aemet fresco pero con fallos acumulados (>= SOURCE_MAX_FAILURES).
                ScheduledJobORM(job_name="aemet_sync", interval_seconds=1800),
                SourceSyncStateORM(
                    source="aemet",
                    last_run_at=now - timedelta(minutes=5),
                    last_success_at=now - timedelta(minutes=5),
                    last_error="boom",
                    consecutive_failures=3,
                ),
                # meteoalarm programada pero sin fila de estado: nunca corrio.
                ScheduledJobORM(job_name="meteoalarm_sync", interval_seconds=3600),
            ]
        )
        await session.commit()

    async with _client(committing_factory) as client:
        response = await client.get("/v1/sources/status")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "degraded"
    by = _by_source(body)
    assert set(by) == {"effis", "ign", "aemet", "meteoalarm"}

    assert by["effis"]["healthy"] is True
    assert by["effis"]["stale"] is False
    assert by["effis"]["interval_seconds"] == 14400

    assert by["ign"]["stale"] is True
    assert by["ign"]["healthy"] is False

    assert by["aemet"]["stale"] is False
    assert by["aemet"]["healthy"] is False
    assert by["aemet"]["consecutive_failures"] == 3
    assert by["aemet"]["has_error"] is True

    never = by["meteoalarm"]
    assert never["last_run_at"] is None
    assert never["last_success_at"] is None
    assert never["seconds_since_success"] is None
    assert never["stale"] is True
    assert never["healthy"] is False

    app.dependency_overrides.clear()


async def test_status_ok_cuando_todo_sano(committing_factory: async_sessionmaker) -> None:
    now = datetime.now(UTC)
    async with committing_factory() as session:
        session.add_all(
            [
                ScheduledJobORM(job_name="effis_sync", interval_seconds=14400),
                SourceSyncStateORM(
                    source="effis",
                    last_run_at=now - timedelta(minutes=10),
                    last_success_at=now - timedelta(minutes=10),
                    consecutive_failures=0,
                ),
                ScheduledJobORM(job_name="ign_sync", interval_seconds=900),
                SourceSyncStateORM(
                    source="ign",
                    last_run_at=now - timedelta(minutes=5),
                    last_success_at=now - timedelta(minutes=5),
                    consecutive_failures=0,
                ),
            ]
        )
        await session.commit()

    async with _client(committing_factory) as client:
        response = await client.get("/v1/sources/status")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert all(s["healthy"] for s in body["sources"])

    app.dependency_overrides.clear()
