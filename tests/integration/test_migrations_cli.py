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


async def _lote_indexes(dsn: str) -> dict[str, bool]:
    # Los indices CONCURRENTLY se construyen fuera de la transaccion de
    # alembic: un build fallido deja el indice INVALID sin error visible.
    conn = await asyncpg.connect(dsn)
    try:
        rows = await conn.fetch(
            "SELECT c.relname, i.indisvalid FROM pg_index i "
            "JOIN pg_class c ON c.oid = i.indexrelid "
            "WHERE c.relname LIKE 'ix_hazard_events_source_%'"
        )
        return {r["relname"]: r["indisvalid"] for r in rows}
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
        assert asyncio.run(_lote_indexes(_plain_dsn(fresh_url))) == {
            "ix_hazard_events_source_created_at": True,
            "ix_hazard_events_source_updated_at": True,
        }
    finally:
        asyncio.run(_drop_db(_plain_dsn(pg_url), name))


async def _seed_before_provinces(dsn: str) -> None:
    # 11.000 sismos en Murcia (tres lotes del relleno) y dos poligonos que
    # tocan Murcia: uno dentro y otro que solapa sobre todo con Almeria.
    conn = await asyncpg.connect(dsn)
    try:
        await conn.execute(
            "INSERT INTO hazard_events (id, source, hazard_type, external_id, geom, severity,"
            " starts_at, attrs, content_hash) "
            "SELECT gen_random_uuid(), 'ign', 'earthquake', 'q' || g,"
            " ST_SetSRID(ST_MakePoint(-1.13, 37.98), 4326), 2, now(), '{}', 'h' || g "
            "FROM generate_series(1, 11000) g"
        )
        for name, polygon in (
            ("vega", "POLYGON((-1.3 38.0,-1.0 38.0,-1.0 38.2,-1.3 38.2,-1.3 38.0))"),
            ("almanzora", "POLYGON((-2.3 37.45,-1.85 37.45,-1.85 37.65,-2.3 37.65,-2.3 37.45))"),
        ):
            await conn.execute(
                "INSERT INTO hazard_events (id, source, hazard_type, external_id, geom, severity,"
                " starts_at, attrs, content_hash) VALUES (gen_random_uuid(), 'aemet',"
                " 'weather_warning', $1, ST_GeomFromText($2, 4326), 2, now(), '{}', $1)",
                name,
                polygon,
            )
    finally:
        await conn.close()


async def _provinces_by_event(dsn: str) -> dict[str, int]:
    conn = await asyncpg.connect(dsn)
    try:
        rows = await conn.fetch(
            "SELECT coalesce(province_code, '--') AS code, count(*) AS n "
            "FROM hazard_events GROUP BY 1"
        )
        valid = await conn.fetchval(
            "SELECT i.indisvalid FROM pg_index i JOIN pg_class c ON c.oid = i.indexrelid "
            "WHERE c.relname = 'ix_hazard_events_province_starts_at'"
        )
        return {**{r["code"]: r["n"] for r in rows}, "index_valid": int(bool(valid))}
    finally:
        await conn.close()


def test_la_provincia_de_cada_evento_se_rellena_en_lo_existente(
    pg_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    name = f"migrations_provinces_{uuid4().hex[:8]}"
    base, _, _ = pg_url.rpartition("/")
    fresh_url = f"{base}/{name}"
    asyncio.run(_create_db(_plain_dsn(pg_url), name))
    try:
        monkeypatch.setattr(settings, "DATABASE_URL", fresh_url)
        cfg = Config(str(ALEMBIC_INI))
        command.upgrade(cfg, "0daefaeba006")
        asyncio.run(_seed_before_provinces(_plain_dsn(fresh_url)))

        command.upgrade(cfg, "head")

        assert asyncio.run(_provinces_by_event(_plain_dsn(fresh_url))) == {
            "30": 11001,
            "04": 1,
            "index_valid": 1,
        }
    finally:
        asyncio.run(_drop_db(_plain_dsn(pg_url), name))
