"""`alembic upgrade head` por la ruta de la CLI (la que usa el deploy).

El resto de la suite migra inyectando una conexion AUTOCOMMIT, que no ejercita
el wiring async de migrations/env.py. Un statement previo a la transaccion de
alembic (el SET statement_timeout de ADR-0017) dejaba la conexion con una
transaccion implicita abierta: alembic no la commiteaba y al cerrar se hacia
rollback de todo, con exit 0. Este test migra una BD vacia por esa ruta.
"""

import asyncio
from uuid import uuid4

import asyncpg
import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory

from app.core.config import settings
from tests.integration.conftest import ALEMBIC_INI

pytestmark = pytest.mark.integration


def _plain_dsn(url: str) -> str:
    return url.replace("postgresql+asyncpg://", "postgresql://")


async def _create_db(admin_dsn: str, name: str) -> None:
    conn = await asyncpg.connect(admin_dsn)
    try:
        await conn.execute(f'CREATE DATABASE "{name}"')
    finally:
        await conn.close()


async def _drop_db(admin_dsn: str, name: str) -> None:
    conn = await asyncpg.connect(admin_dsn)
    try:
        await conn.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
    finally:
        await conn.close()


async def _state(dsn: str) -> tuple[str | None, bool]:
    conn = await asyncpg.connect(dsn)
    try:
        has_version = await conn.fetchval(
            "SELECT to_regclass('public.alembic_version') IS NOT NULL"
        )
        version = (
            await conn.fetchval("SELECT version_num FROM alembic_version") if has_version else None
        )
        has_events = await conn.fetchval("SELECT to_regclass('public.hazard_events') IS NOT NULL")
        return version, has_events
    finally:
        await conn.close()


def test_upgrade_por_cli_deja_la_bd_en_head(pg_url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    name = f"migrations_cli_{uuid4().hex[:8]}"
    base, _, _ = pg_url.rpartition("/")
    fresh_url = f"{base}/{name}"
    asyncio.run(_create_db(_plain_dsn(pg_url), name))
    try:
        monkeypatch.setattr(settings, "DATABASE_URL", fresh_url)
        cfg = Config(str(ALEMBIC_INI))

        command.upgrade(cfg, "head")

        version, has_events = asyncio.run(_state(_plain_dsn(fresh_url)))
        assert version == ScriptDirectory.from_config(cfg).get_current_head()
        assert has_events
    finally:
        asyncio.run(_drop_db(_plain_dsn(pg_url), name))
