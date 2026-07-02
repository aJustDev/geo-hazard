from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from testcontainers.postgres import PostgresContainer

import app.core.db_registry  # noqa: F401 - registra todas las tablas en Base.metadata

ALEMBIC_INI = Path(__file__).resolve().parents[2] / "alembic.ini"

_TABLES = "hazard_events, source_sync_state, outbox_events, scheduled_jobs"


@pytest.fixture(scope="session")
def pg_url() -> Iterator[str]:
    with PostgresContainer("postgis/postgis:17-3.5", driver="asyncpg") as pg:
        yield pg.get_connection_url()


def _run_alembic_upgrade(sync_connection: Connection) -> None:
    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("sqlalchemy.url", str(sync_connection.engine.url))
    cfg.attributes["connection"] = sync_connection
    command.upgrade(cfg, "head")


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def async_engine(pg_url: str) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(pg_url, echo=False)
    async with engine.connect() as conn:
        ac_conn = await conn.execution_options(isolation_level="AUTOCOMMIT")
        await ac_conn.run_sync(_run_alembic_upgrade)
    yield engine
    await engine.dispose()


@pytest.fixture(scope="session")
def session_factory(async_engine: AsyncEngine) -> async_sessionmaker:
    return async_sessionmaker(async_engine, expire_on_commit=False)


@pytest_asyncio.fixture(loop_scope="session")
async def db_session(session_factory: async_sessionmaker) -> AsyncIterator:
    """AsyncSession con rollback al final: aislamiento total entre tests.

    Los repos solo hacen flush() (nunca commit), asi que el rollback descarta
    todo lo escrito en el test.
    """
    async with session_factory() as session:
        yield session
        await session.rollback()


@pytest_asyncio.fixture(loop_scope="session")
async def committing_factory(
    pg_url: str, async_engine: AsyncEngine
) -> AsyncIterator[async_sessionmaker]:
    """Factory que SI commitea, para probar workers/handlers que abren su
    propia sesion. Depende de `async_engine` para que el esquema (Alembic) ya
    exista. Trunca las tablas antes y despues para aislar.
    """
    _ = async_engine
    engine = create_async_engine(pg_url, poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def _truncate() -> None:
        async with factory() as session:
            await session.execute(text(f"TRUNCATE {_TABLES} RESTART IDENTITY CASCADE"))
            await session.commit()

    await _truncate()
    try:
        yield factory
    finally:
        await _truncate()
        await engine.dispose()
