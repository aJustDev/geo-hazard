import functools
from collections.abc import Callable

import anyio


async def run_blocking[T](func: Callable[..., T], *args: object, **kwargs: object) -> T:
    """Ejecuta una funcion sincrona CPU-bound en el threadpool para no
    bloquear el unico event loop. La propagacion SGP4 (skyfield) y otros
    calculos pesados serializarian todas las requests del worker si se
    ejecutaran inline en el loop.
    """
    return await anyio.to_thread.run_sync(functools.partial(func, *args, **kwargs))
