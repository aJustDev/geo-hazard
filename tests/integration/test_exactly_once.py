"""Invariante exactly-once del nucleo (E2): con dos workers compitiendo por la
misma fila, el despacho ocurre UNA sola vez.

Es la razon de ser del FOR UPDATE SKIP LOCKED del outbox y del claim atomico
(UPDATE ... WHERE status='PENDING' RETURNING) de los jobs. La contienda es
real a nivel de BD: committing_factory usa NullPool, asi que cada sesion es
una conexion fisica distinta y las dos corrutinas de asyncio.gather pelean por
la fila en Postgres, no en memoria.
"""

import asyncio
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.events import worker as outbox_worker_module
from app.core.events.bus import EventBus
from app.core.events.dispatcher import dispatcher
from app.core.events.models import OutboxEventORM
from app.core.events.worker import OutboxWorker
from app.core.jobs import worker as jobs_worker_module
from app.core.jobs.models import ScheduledJobORM
from app.core.jobs.registry import job_registry
from app.core.jobs.worker import JobWorker

pytestmark = [pytest.mark.integration, pytest.mark.asyncio(loop_scope="session")]


@pytest.fixture
def isolated_dispatcher() -> Iterator[None]:
    snapshot = {k: list(v) for k, v in dispatcher._handlers.items()}
    yield
    dispatcher._handlers.clear()
    dispatcher._handlers.update(snapshot)


@pytest.fixture
def isolated_registry() -> Iterator[None]:
    snapshot = dict(job_registry._jobs)
    yield
    job_registry._jobs.clear()
    job_registry._jobs.update(snapshot)


async def test_outbox_despacha_una_vez_con_dos_workers(
    committing_factory: async_sessionmaker,
    monkeypatch: pytest.MonkeyPatch,
    isolated_dispatcher: None,
) -> None:
    monkeypatch.setattr(outbox_worker_module, "async_session_factory", committing_factory)
    calls: list[dict] = []

    @dispatcher.register("test.exactly_once")
    async def handler(payload: dict) -> None:
        calls.append(payload)

    async with committing_factory() as session:
        await EventBus(session).publish("test.exactly_once", {"n": 1})
        await session.commit()

    # Dos workers drenando a la vez el mismo evento PENDING.
    await asyncio.gather(
        OutboxWorker()._process_batch(),
        OutboxWorker()._process_batch(),
    )

    assert calls == [{"n": 1}]  # exactamente un despacho
    async with committing_factory() as session:
        row = (
            await session.execute(
                select(OutboxEventORM).where(OutboxEventORM.event_type == "test.exactly_once")
            )
        ).scalar_one()
    assert row.status == "PROCESSED"


async def test_job_se_ejecuta_una_vez_con_dos_workers(
    committing_factory: async_sessionmaker,
    monkeypatch: pytest.MonkeyPatch,
    isolated_registry: None,
) -> None:
    monkeypatch.setattr(jobs_worker_module, "async_session_factory", committing_factory)
    calls: list[None] = []

    async def handler() -> None:
        calls.append(None)

    job_registry._jobs["test.exactly_once"] = handler
    async with committing_factory() as session:
        job = ScheduledJobORM(
            job_name="test.exactly_once",
            interval_seconds=3600,
            status="PENDING",
            next_run_at=datetime.now(UTC) - timedelta(seconds=1),
        )
        session.add(job)
        await session.commit()
        job_id = job.id

    # Dos workers reclamando el mismo job due a la vez.
    w1, w2 = JobWorker(), JobWorker()
    await asyncio.gather(w1._execute_job(job_id), w2._execute_job(job_id))

    assert calls == [None]  # exactamente una ejecucion
    async with committing_factory() as session:
        row = (
            await session.execute(
                select(ScheduledJobORM).where(ScheduledJobORM.job_name == "test.exactly_once")
            )
        ).scalar_one()
    assert row.run_count == 1
    assert row.status == "PENDING"
