import functools
from collections.abc import Callable

import anyio


async def run_blocking[T](func: Callable[..., T], *args: object, **kwargs: object) -> T:
    """Ejecuta una funcion sincrona CPU-bound en el threadpool para no
    bloquear el unico event loop. DuckDB (consultas analiticas, escritura de
    snapshots GeoParquet) es sincrono y serializaria todas las requests del
    worker si se ejecutara inline en el loop.
    """
    return await anyio.to_thread.run_sync(functools.partial(func, *args, **kwargs))
