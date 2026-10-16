import asyncio
import contextlib
import logging
import random
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.core.config import settings
from app.core.db import async_session_factory
from app.core.events.dispatcher import dispatcher
from app.core.events.models import OutboxEventORM

logger = logging.getLogger(__name__)

BATCH_SIZE = 50
MAX_BACKOFF_HOURS = 1
MAX_ERROR_BACKOFF_SECONDS = 60


class OutboxWorker:
    def __init__(self) -> None:
        self._task: asyncio.Task[None] | None = None
        self._shutdown_event = asyncio.Event()

    async def start(self) -> None:
        self._shutdown_event.clear()
        self._task = asyncio.create_task(self._run(), name="outbox-worker")
        logger.debug("Outbox worker started")

    async def stop(self) -> None:
        self._shutdown_event.set()
        if self._task and not self._task.done():
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        logger.info("Outbox worker stopped")

    # Main loop: poll puro (ADR-0002, enmienda 2026-10-16). La latencia que
    # manda es la cadencia de sync de las fuentes, no el intervalo de poll.

    async def _run(self) -> None:
        consecutive_errors = 0
        while not self._shutdown_event.is_set():
            delay = settings.OUTBOX_POLL_INTERVAL_SECONDS
            try:
                await self._process_batch()
                consecutive_errors = 0
            except asyncio.CancelledError:
                raise
            except Exception:
                # BD caida: backoff exponencial para no escribir una traza
                # por tick mientras dure la caida.
                consecutive_errors += 1
                delay = max(delay, min(2**consecutive_errors, MAX_ERROR_BACKOFF_SECONDS))
                logger.exception("Outbox worker error, retrying in %.0fs", delay)

            try:
                await asyncio.wait_for(self._shutdown_event.wait(), timeout=delay)
                break
            except TimeoutError:
                pass

    # Batch processing

    async def _process_batch(self) -> None:
        # Un evento por transaccion: el lock FOR UPDATE SKIP LOCKED se mantiene
        # hasta el commit de ESE evento. Hacer un solo SELECT del lote y
        # commitear dentro del bucle liberaria los locks de las filas aun
        # PENDING -> un segundo worker (replica / rolling deploy) las
        # despacharia por duplicado.
        for _ in range(BATCH_SIZE):
            async with async_session_factory() as session:
                stmt = (
                    select(OutboxEventORM)
                    .where(OutboxEventORM.status == "PENDING")
                    .where(OutboxEventORM.scheduled_at <= datetime.now(UTC))
                    .order_by(OutboxEventORM.scheduled_at)
                    .limit(1)
                    .with_for_update(skip_locked=True)
                )
                event = (await session.execute(stmt)).scalars().first()
                if event is None:
                    return
                await self._handle_event(session, event)
                await session.commit()

    async def _handle_event(self, session: AsyncSession, event: OutboxEventORM) -> None:
        completed = {
            name for name, info in (event.handler_state or {}).items() if info.get("status") == "ok"
        }

        dispatch_result = await dispatcher.dispatch(
            event.event_type,
            event.payload,
            completed_handlers=completed,
        )

        new_state = dict(event.handler_state or {})
        now_iso = datetime.now(UTC).isoformat()
        for r in dispatch_result.results:
            if r.skipped:
                continue
            entry: dict[str, str] = {"status": "ok" if r.success else "failed", "at": now_iso}
            if r.error:
                entry["error"] = r.error[:500]
            new_state[r.handler_name] = entry
        event.handler_state = new_state
        flag_modified(event, "handler_state")

        if dispatch_result.all_succeeded:
            event.status = "PROCESSED"
            event.processed_at = datetime.now(UTC)
            logger.info("Event %s processed (type=%s)", event.id, event.event_type)
        else:
            event.retry_count += 1
            event.last_error = dispatch_result.errors_summary

            if event.retry_count >= event.max_retries:
                event.status = "FAILED"
                logger.critical(
                    "Event %s FAILED after %d retries (type=%s): %s",
                    event.id,
                    event.retry_count,
                    event.event_type,
                    dispatch_result.errors_summary[:500],
                )
            else:
                backoff_seconds = min(
                    2**event.retry_count + random.uniform(0, 5),  # noqa: S311
                    MAX_BACKOFF_HOURS * 3600,
                )
                event.scheduled_at = datetime.now(UTC) + timedelta(seconds=backoff_seconds)
                logger.warning(
                    "Event %s retry %d/%d scheduled at %s (type=%s)",
                    event.id,
                    event.retry_count,
                    event.max_retries,
                    event.scheduled_at,
                    event.event_type,
                )

        await session.flush()
