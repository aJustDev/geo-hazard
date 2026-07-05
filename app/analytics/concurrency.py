"""Acota la concurrencia del plano analitico DuckDB (ADR-0017).

La conexion DuckDB es unica y con limites conservadores (threads=2,
memory_limit=512MB) porque convive con la API y Postgres en el mismo host.
Bajo el threadpool de ~40 hilos que sirve las peticiones, varias consultas
pesadas a la vez se reparten esos 512 MB y pueden dar OOM (un 500 opaco). El
semaforo las acota a ANALYTICS_MAX_CONCURRENCY; si no hay hueco en un margen
corto, se rechaza con 503 + Retry-After en vez de tumbar el proceso.
"""

from collections.abc import Callable

import anyio

from app.core.concurrency import run_blocking
from app.core.config import settings
from app.core.exceptions.exceptions import ServiceOverloadedError

# CapacityLimiter (no un Semaphore de asyncio) para encajar con anyio, que es
# lo que usa run_blocking por debajo.
_limiter = anyio.CapacityLimiter(settings.ANALYTICS_MAX_CONCURRENCY)


async def run_analytics[T](func: Callable[..., T], *args: object, **kwargs: object) -> T:
    """Ejecuta una query DuckDB (sincrona) bajo el limite de concurrencia.

    Adquiere un slot con un timeout corto: si el plano esta saturado, no se
    encola indefinidamente, se rechaza con ServiceOverloadedError (503). El
    timeout SOLO cubre la espera por un slot, no la duracion de la query.
    """
    try:
        with anyio.fail_after(settings.ANALYTICS_ACQUIRE_TIMEOUT_SECONDS):
            await _limiter.acquire()
    except TimeoutError:
        raise ServiceOverloadedError(
            "analytics plane is busy, retry shortly", retry_after=1
        ) from None
    try:
        return await run_blocking(func, *args, **kwargs)
    finally:
        _limiter.release()


__all__ = ["run_analytics"]
