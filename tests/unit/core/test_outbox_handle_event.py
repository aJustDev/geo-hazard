import asyncio
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock

import pytest

from app.core.events import worker as worker_module
from app.core.events.dispatcher import dispatcher
from app.core.events.models import OutboxEventORM
from app.core.events.worker import OutboxWorker


def _event(**kwargs: Any) -> OutboxEventORM:
    base: dict[str, Any] = {
        "event_type": "x",
        "payload": {},
        "status": "PENDING",
        "retry_count": 0,
        "max_retries": 3,
        "handler_state": {},
    }
    base.update(kwargs)
    return OutboxEventORM(**base)


async def test_handle_event_sin_handler_reintenta_en_vez_de_procesar() -> None:
    worker = OutboxWorker()
    session = AsyncMock()
    event = _event(event_type="no.handlers.here")

    await worker._handle_event(session, event)

    assert event.status == "PENDING"
    assert event.processed_at is None
    assert event.retry_count == 1
    assert "no handlers registered" in event.last_error
    session.flush.assert_awaited_once()


async def test_handle_event_failure_increments_retry_and_backs_off(
    isolated_dispatcher: None,
) -> None:
    @dispatcher.register("outbox.test.boom")
    async def _boom(payload: dict[str, Any]) -> None:
        raise RuntimeError("x")

    worker = OutboxWorker()
    session = AsyncMock()
    base = datetime(2024, 1, 1, tzinfo=UTC)
    event = _event(event_type="outbox.test.boom", scheduled_at=base)

    await worker._handle_event(session, event)

    assert event.status == "PENDING"
    assert event.retry_count == 1
    assert event.scheduled_at > base
    assert event.handler_state["_boom"]["status"] == "failed"


async def test_handle_event_dead_letters_when_retries_exhausted(
    isolated_dispatcher: None,
) -> None:
    # La rama mas importante en operacion: al agotar max_retries el evento
    # pasa a FAILED con last_error y NO se reprograma (dead-letter).
    @dispatcher.register("outbox.test.dead")
    async def _dead(payload: dict[str, Any]) -> None:
        raise RuntimeError("fallo permanente")

    worker = OutboxWorker()
    session = AsyncMock()
    base = datetime(2024, 1, 1, tzinfo=UTC)
    event = _event(event_type="outbox.test.dead", retry_count=2, scheduled_at=base)

    await worker._handle_event(session, event)

    assert event.status == "FAILED"
    assert event.retry_count == 3
    assert "fallo permanente" in event.last_error
    assert event.scheduled_at == base  # sin backoff: no habra mas intentos
    session.flush.assert_awaited_once()


async def test_run_sobrevive_a_un_error_de_bd_y_sigue_haciendo_poll(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(worker_module.settings, "OUTBOX_POLL_INTERVAL_SECONDS", 0.01)
    monkeypatch.setattr(worker_module, "MAX_ERROR_BACKOFF_SECONDS", 0.01)
    worker = OutboxWorker()
    calls = 0

    async def _batch() -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise ConnectionError("bd caida")
        if calls == 3:
            worker._shutdown_event.set()

    monkeypatch.setattr(worker, "_process_batch", _batch)

    await asyncio.wait_for(worker._run(), timeout=2)

    assert calls == 3
