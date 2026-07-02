import asyncio
import logging
import os
import time
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.config import settings

logger = logging.getLogger(__name__)

DB_CONNECT_TIMEOUT = 3


def check_utc_timezone() -> None:
    """Verifica que el proceso opera en UTC. Fail-fast en prod.

    Las fuentes emiten timestamps con offset (CAP usa hora local peninsular) y
    el dominio compara ventanas de validez con now(); el proceso debe operar en
    UTC para que esas comparaciones sean estables. En dev se advierte; en prod
    se aborta el arranque.
    """
    local_tz = (time.tzname[0] or "").upper() if time.tzname else ""
    env_tz = (os.environ.get("TZ") or "").upper()
    utc_variants = {"UTC", "GMT", "UCT", "UNIVERSAL", ""}
    is_utc = local_tz in utc_variants or env_tz == "UTC"
    if is_utc:
        return

    message = (
        f"Process timezone is not UTC (tzname={time.tzname}, TZ={env_tz}). "
        "Set TZ=UTC in the deploy environment."
    )
    if settings.ENVIRONMENT == "prod":
        raise RuntimeError(message)
    logger.warning(message)


def check_data_dir() -> None:
    """Verifica que DATA_DIR existe y es escribible. Fail-fast siempre.

    El export GeoParquet corre dentro de un handler del outbox horas despues
    del arranque; un volumen sin montar o de solo lectura fallaria tarde y en
    bucle de reintentos. Mejor abortar el arranque con un mensaje claro.
    """
    data_dir = Path(settings.DATA_DIR)
    exports = data_dir / "exports"
    try:
        exports.mkdir(parents=True, exist_ok=True)
        probe = exports / ".write-probe"
        probe.touch()
        probe.unlink()
    except OSError as exc:
        raise RuntimeError(f"DATA_DIR {settings.DATA_DIR!r} is not writable: {exc}") from exc


async def check_database(engine: AsyncEngine) -> str:
    try:
        async with asyncio.timeout(DB_CONNECT_TIMEOUT), engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return "OK"
    except Exception as exc:
        logger.warning("database not available: %s", exc)
        return "UNAVAILABLE"


__all__ = ["check_data_dir", "check_database", "check_utc_timezone"]
