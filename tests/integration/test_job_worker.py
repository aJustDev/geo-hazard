from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.jobs import worker as worker_module
from app.core.jobs.models import ScheduledJobORM
from app.core.jobs.registry import job_registry
from app.core.jobs.worker import JobWorker

pytestmark = [pytest.mark.integration, pytest.mark.asyncio(loop_scope="session")]


@pytest.fixture
def isolated_registry() -> Iterator[None]:
    snapshot = dict(job_registry._jobs)
    yield
    job_registry._jobs.clear()
    job_registry._jobs.update(snapshot)


async def _seed_job(factory: async_sessionmaker, **kwargs: object) -> None:
    async with factory() as session:
        session.add(ScheduledJobORM(**kwargs))
        await session.commit()


async def _fetch(factory: async_sessionmaker, job_name: str) -> ScheduledJobORM:
    async with factory() as session:
        return (
            await session.execute(
                select(ScheduledJobORM).where(ScheduledJobORM.job_name == job_name)
            )
        ).scalar_one()


async def test_executes_due_job_and_reschedules(
    committing_factory: async_sessionmaker,
    monkeypatch: pytest.MonkeyPatch,
    isolated_registry: None,
) -> None:
    monkeypatch.setattr(worker_module, "async_session_factory", committing_factory)
    calls: list[None] = []

    async def handler() -> None:
        calls.append(None)

    job_registry._jobs["test.tick"] = handler
    await _seed_job(
        committing_factory,
        job_name="test.tick",
        interval_seconds=60,
        status="PENDING",
        next_run_at=datetime.now(UTC) - timedelta(seconds=1),
    )

    await JobWorker()._process_due_jobs()

    assert len(calls) == 1
    row = await _fetch(committing_factory, "test.tick")
    assert row.status == "PENDING"
    assert row.run_count == 1
    assert row.last_run_at is not None
    assert row.next_run_at > datetime.now(UTC)
    assert row.claimed_by is None
    assert row.lease_until is None


async def test_recovers_stale_running_job(
    committing_factory: async_sessionmaker,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(worker_module, "async_session_factory", committing_factory)
    await _seed_job(
        committing_factory,
        job_name="test.zombie",
        interval_seconds=60,
        status="RUNNING",
        claimed_by="dead-worker",
        lease_until=datetime.now(UTC) - timedelta(minutes=5),
        next_run_at=datetime.now(UTC),
    )

    await JobWorker()._recover_stale_jobs()

    row = await _fetch(committing_factory, "test.zombie")
    assert row.status == "PENDING"
    assert row.claimed_by is None
    assert row.lease_until is None
