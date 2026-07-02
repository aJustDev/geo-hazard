from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock

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


async def test_handle_event_no_handler_marks_processed() -> None:
    worker = OutboxWorker()
    session = AsyncMock()
    event = _event(event_type="no.handlers.here")

    await worker._handle_event(session, event)

    assert event.status == "PROCESSED"
    assert event.processed_at is not None
    session.flush.assert_awaited_once()


async def test_handle_event_failure_increments_retry_and_backs_off() -> None:
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
