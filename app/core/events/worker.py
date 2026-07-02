import asyncio
import contextlib
import logging
import random
from datetime import UTC, datetime, timedelta

import asyncpg
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.core.config import settings
from app.core.db import async_session_factory
from app.core.events.dispatcher import dispatcher
from app.core.events.models import OutboxEventORM

logger = logging.getLogger(__name__)

CHANNEL = "geohazard_outbox_channel"
BATCH_SIZE = 50
MAX_BACKOFF_HOURS = 1
MAX_RECONNECT_DELAY = 60


def _build_asyncpg_dsn() -> str:
    """DSN plano (sin +asyncpg) para la conexion raw que hace LISTEN."""
    return (
        f"postgresql://{settings.DB_USER}:{settings.DB_PASSWORD}"
        f"@{settings.DB_HOST}:{settings.DB_PORT}/{settings.DB_NAME}"
    )


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

    # Main loop

    async def _run(self) -> None:
        reconnect_attempt = 0

        while not self._shutdown_event.is_set():
            conn: asyncpg.Connection | None = None
            try:
                conn = await asyncpg.connect(_build_asyncpg_dsn())
                await conn.add_listener(CHANNEL, self._on_notify)
                reconnect_attempt = 0

                while not self._shutdown_event.is_set():
                    # Espera NOTIFY o timeout de poll. El poll es la fuente de
                    # verdad: _on_notify solo despierta antes (ver nota abajo).
                    try:
                        await asyncio.wait_for(
                            self._shutdown_event.wait(),
                            timeout=settings.OUTBOX_POLL_INTERVAL_SECONDS,
                        )
                        break
                    except TimeoutError:
                        pass

                    try:
                        await conn.execute("SELECT 1")
                    except Exception:
                        logger.warning("Heartbeat failed, reconnecting...")
                        break

                    await self._process_batch()

            except asyncio.CancelledError:
                raise
            except Exception:
                reconnect_attempt += 1
                delay = min(2**reconnect_attempt, MAX_RECONNECT_DELAY)
                logger.exception("Outbox worker connection error, retrying in %ds", delay)
                await asyncio.sleep(delay)
            finally:
                if conn and not conn.is_closed():
                    with contextlib.suppress(Exception):
                        await conn.remove_listener(CHANNEL, self._on_notify)
                    await conn.close()

    def _on_notify(
        self,
        connection: asyncpg.Connection,
        pid: int,
        channel: str,
        payload: str,
    ) -> None:
        # Solo loguea: el procesado lo dispara el poll. La correccion no
        # depende del NOTIFY (un notify perdido no pierde el evento).
        logger.debug("Received NOTIFY on %s: %s", channel, payload)

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
