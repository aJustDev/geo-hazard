"""Entorno Alembic: wiring async para geo-hazard.

Lee la URL desde app.core.config.settings (la misma config que la app).
Soporta dos modos:

1. CLI (`uv run alembic upgrade head`): crea un AsyncEngine y ejecuta.
2. Tests de integracion: el conftest inyecta una conexion existente via
   `config.attributes["connection"]` (no crea un engine nuevo).

Usa los helpers de geoalchemy2 para que las columnas Geometry y sus indices
espaciales se rendericen bien en autogenerate.
"""

import asyncio

from alembic import context
from geoalchemy2 import alembic_helpers
from sqlalchemy import engine_from_config, pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.core import db_registry as _db_registry  # noqa: F401 - registra modelos y handlers
from app.core.config import settings
from app.core.db import Base

config = context.config
target_metadata = Base.metadata


def _configure_and_run(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
        include_schemas=False,
        process_revision_directives=alembic_helpers.writer,
        render_item=alembic_helpers.render_item,
        include_object=alembic_helpers.include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_offline() -> None:
    """Modo offline: genera SQL sin conectar a la BD."""
    context.configure(
        url=settings.DATABASE_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        compare_type=True,
        compare_server_default=True,
        dialect_opts={"paramstyle": "named"},
        render_item=alembic_helpers.render_item,
        include_object=alembic_helpers.include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


async def _run_async_migrations() -> None:
    ini_section = config.get_section(config.config_ini_section) or {}
    ini_section["sqlalchemy.url"] = settings.DATABASE_URL
    connectable = async_engine_from_config(
        ini_section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(_configure_and_run)
    await connectable.dispose()


def run_migrations_online() -> None:
    """Modo online. Usa la conexion inyectada (tests) o crea un AsyncEngine."""
    injected_connection: Connection | None = config.attributes.get("connection")
    if injected_connection is not None:
        _configure_and_run(injected_connection)
        return

    url = settings.DATABASE_URL
    if "+asyncpg" in url or "+aiosqlite" in url:
        asyncio.run(_run_async_migrations())
        return

    ini_section = config.get_section(config.config_ini_section) or {}
    ini_section["sqlalchemy.url"] = url
    connectable = engine_from_config(ini_section, prefix="sqlalchemy.", poolclass=pool.NullPool)
    with connectable.connect() as connection:
        _configure_and_run(connection)


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
