import asyncio
from collections.abc import Iterator

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.events import worker as worker_module
from app.core.events.bus import EventBus
from app.core.events.dispatcher import dispatcher
from app.core.events.models import OutboxEventORM
from app.core.events.worker import OutboxWorker

pytestmark = [pytest.mark.integration, pytest.mark.asyncio(loop_scope="session")]


@pytest.fixture
def isolated_dispatcher() -> Iterator[None]:
    snapshot = {k: list(v) for k, v in dispatcher._handlers.items()}
    yield
    dispatcher._handlers.clear()
    dispatcher._handlers.update(snapshot)


async def _fetch(factory: async_sessionmaker, event_type: str) -> OutboxEventORM:
    async with factory() as session:
        return (
            await session.execute(
                select(OutboxEventORM).where(OutboxEventORM.event_type == event_type)
            )
        ).scalar_one()


async def test_publish_then_process_marks_processed(
    committing_factory: async_sessionmaker,
    monkeypatch: pytest.MonkeyPatch,
    isolated_dispatcher: None,
) -> None:
    """Ciclo completo: publish (misma transaccion) -> worker -> PROCESSED.

    Es el contrato central del outbox: el evento se persiste con la escritura
    de dominio y el worker lo despacha exactamente una vez al handler.
    """
    monkeypatch.setattr(worker_module, "async_session_factory", committing_factory)
    received: list[dict] = []

    @dispatcher.register("test.echo")
    async def handler(payload: dict) -> None:
        received.append(payload)

    async with committing_factory() as session:
        await EventBus(session).publish("test.echo", {"answer": 42})
        await session.commit()

    await OutboxWorker()._process_batch()

    assert received == [{"answer": 42}]
    row = await _fetch(committing_factory, "test.echo")
    assert row.status == "PROCESSED"
    assert row.processed_at is not None
    assert row.handler_state["handler"]["status"] == "ok"


async def test_failing_handler_is_rescheduled_with_backoff(
    committing_factory: async_sessionmaker,
    monkeypatch: pytest.MonkeyPatch,
    isolated_dispatcher: None,
) -> None:
    monkeypatch.setattr(worker_module, "async_session_factory", committing_factory)

    @dispatcher.register("test.boom")
    async def handler(payload: dict) -> None:
        raise RuntimeError("fallo simulado")

    async with committing_factory() as session:
        await EventBus(session).publish("test.boom", {})
        await session.commit()

    await OutboxWorker()._process_batch()

    row = await _fetch(committing_factory, "test.boom")
    assert row.status == "PENDING"
    assert row.retry_count == 1
    assert row.last_error is not None
    assert row.handler_state["handler"]["status"] == "failed"


async def test_worker_lifecycle_procesa_en_segundo_plano(
    committing_factory: async_sessionmaker,
    monkeypatch: pytest.MonkeyPatch,
    isolated_dispatcher: None,
    pg_url: str,
) -> None:
    """Ciclo de vida real: start() -> LISTEN + poll -> dispatch -> stop().

    Ejercita el bucle _run completo (conexion asyncpg, heartbeat, espera con
    timeout y limpieza del listener al parar), que el resto de tests puentea
    llamando a _process_batch directamente.
    """
    monkeypatch.setattr(worker_module, "async_session_factory", committing_factory)
    monkeypatch.setattr(worker_module, "_build_asyncpg_dsn", lambda: pg_url.replace("+asyncpg", ""))
    monkeypatch.setattr(worker_module.settings, "OUTBOX_POLL_INTERVAL_SECONDS", 0.05)

    received: list[dict] = []

    @dispatcher.register("test.lifecycle")
    async def handler(payload: dict) -> None:
        received.append(payload)

    async with committing_factory() as session:
        await EventBus(session).publish("test.lifecycle", {"n": 1})
        await session.commit()

    worker = OutboxWorker()
    await worker.start()
    try:
        for _ in range(100):  # hasta ~5 s
            await asyncio.sleep(0.05)
            if received:
                break
    finally:
        await worker.stop()

    assert received == [{"n": 1}]
    row = await _fetch(committing_factory, "test.lifecycle")
    assert row.status == "PROCESSED"
