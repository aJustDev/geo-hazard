import asyncio
import contextlib
import logging
import os
import socket
import traceback
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import or_, select, update

from app.core.config import settings
from app.core.db import async_session_factory
from app.core.jobs.models import ScheduledJobORM
from app.core.jobs.registry import job_registry

logger = logging.getLogger(__name__)

BATCH_SIZE = 10


class JobWorker:
    def __init__(self) -> None:
        self._task: asyncio.Task[None] | None = None
        self._shutdown_event = asyncio.Event()
        self._worker_id = f"{socket.gethostname()}:{os.getpid()}"

    async def start(self) -> None:
        self._shutdown_event.clear()
        self._task = asyncio.create_task(self._run(), name="job-worker")
        logger.debug("Job worker started (id=%s)", self._worker_id)

    async def stop(self) -> None:
        self._shutdown_event.set()
        if self._task and not self._task.done():
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        logger.info("Job worker stopped")

    # Main loop

    async def _run(self) -> None:
        while not self._shutdown_event.is_set():
            try:
                await self._recover_stale_jobs()
                await self._process_due_jobs()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Job worker error")

            try:
                await asyncio.wait_for(
                    self._shutdown_event.wait(),
                    timeout=settings.JOB_POLL_INTERVAL_SECONDS,
                )
                break
            except TimeoutError:
                pass

    # Stale recovery: libera filas RUNNING cuyo lease expiro (zombi tras el
    # crash del worker que las claimo). El filtro IS NULL cubre filas que
    # quedaran en RUNNING sin lease tras un deploy.

    async def _recover_stale_jobs(self) -> None:
        async with async_session_factory() as session:
            stmt = (
                update(ScheduledJobORM)
                .where(ScheduledJobORM.status == "RUNNING")
                .where(
                    or_(
                        ScheduledJobORM.lease_until.is_(None),
                        ScheduledJobORM.lease_until < datetime.now(UTC),
                    )
                )
                .values(status="PENDING", claimed_by=None, lease_until=None)
            )
            result = await session.execute(stmt)
            await session.commit()
            if result.rowcount:  # type: ignore[attr-defined]
                logger.warning("Recovered %d stale RUNNING jobs", result.rowcount)  # type: ignore[attr-defined]

    # Procesado: SELECT ligero de ids candidatos sin lock; cada job se claima
    # atomicamente en su propia transaccion via `_execute_job`.

    async def _process_due_jobs(self) -> None:
        async with async_session_factory() as session:
            stmt = (
                select(ScheduledJobORM.id)
                .where(ScheduledJobORM.status == "PENDING")
                .where(ScheduledJobORM.next_run_at <= datetime.now(UTC))
                .order_by(ScheduledJobORM.next_run_at)
                .limit(BATCH_SIZE)
            )
            result = await session.execute(stmt)
            candidate_ids = list(result.scalars().all())

        for job_id in candidate_ids:
            await self._execute_job(job_id)

    async def _execute_job(self, job_id: uuid.UUID) -> None:
        # Fase 1: claim atomico. UPDATE ... RETURNING garantiza que solo un
        # worker pasa la fila de PENDING a RUNNING. rowcount=0 -> otro worker
        # se la llevo entre el SELECT de candidatos y aqui.
        async with async_session_factory() as session:
            lease_until = datetime.now(UTC) + timedelta(seconds=settings.JOB_LEASE_SECONDS)
            claim_stmt = (
                update(ScheduledJobORM)
                .where(ScheduledJobORM.id == job_id)
                .where(ScheduledJobORM.status == "PENDING")
                .where(ScheduledJobORM.next_run_at <= datetime.now(UTC))
                .values(
                    status="RUNNING",
                    claimed_by=self._worker_id,
                    lease_until=lease_until,
                    updated_at=datetime.now(UTC),
                )
                .returning(ScheduledJobORM.job_name, ScheduledJobORM.interval_seconds)
            )
            row = (await session.execute(claim_stmt)).one_or_none()
            await session.commit()
            if row is None:
                return
            job_name, interval_seconds = row

        # Fase 2: ejecuta el handler (sin transaccion abierta).
        handler = job_registry.get(job_name)
        error: str | None = None

        if handler is None:
            error = f"No handler registered for job '{job_name}'"
            logger.warning(error)
        else:
            start = datetime.now(UTC)
            try:
                await asyncio.wait_for(handler(), timeout=settings.JOB_HANDLER_TIMEOUT_SECONDS)
                elapsed_ms = (datetime.now(UTC) - start).total_seconds() * 1000
                logger.info("Job '%s' done (%.0fms, PID=%d)", job_name, elapsed_ms, os.getpid())
            except Exception:
                error = traceback.format_exc()
                logger.exception("Job '%s' failed (PID=%d)", job_name, os.getpid())

        # Fase 3: reprograma. Incremento atomico de run_count en SQL para
        # evitar lost-update si dos workers tocaran la misma fila.
        async with async_session_factory() as session:
            now = datetime.now(UTC)
            reschedule_stmt = (
                update(ScheduledJobORM)
                .where(ScheduledJobORM.id == job_id)
                .values(
                    status="PENDING",
                    claimed_by=None,
                    lease_until=None,
                    next_run_at=now + timedelta(seconds=interval_seconds),
                    last_run_at=now,
                    run_count=ScheduledJobORM.run_count + 1,
                    last_error=error[-500:] if error else None,
                    updated_at=now,
                )
            )
            await session.execute(reschedule_stmt)
            await session.commit()
