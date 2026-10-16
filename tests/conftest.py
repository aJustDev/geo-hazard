import os
from collections.abc import Iterator

import pytest

# El rate limiting (slowapi) mantiene contadores en memoria a nivel de proceso:
# entre tests se acumularian peticiones y algun test que dispara varias
# llamadas podria dar 429 de forma no determinista. Se desactiva para toda la
# suite ANTES de que se importe app.core.config (el singleton `settings` lee el
# entorno al construirse). El wiring del limiter se prueba de forma aislada en
# tests/unit/core/test_rate_limit.py, que monta su propio limiter habilitado.
os.environ.setdefault("RATE_LIMIT_ENABLED", "false")


# Los registros de handlers (dispatcher del outbox y job_registry) son
# singletons de proceso. Un test que registre handlers propios debe pedir estas
# fixtures: restauran el estado al terminar y no contaminan tests posteriores.
# Imports locales: este modulo fija el entorno ANTES de importar la app.


@pytest.fixture
def isolated_dispatcher() -> Iterator[None]:
    from app.core.events.dispatcher import dispatcher

    snapshot = {k: list(v) for k, v in dispatcher._handlers.items()}
    yield
    dispatcher._handlers.clear()
    dispatcher._handlers.update(snapshot)


@pytest.fixture
def isolated_registry() -> Iterator[None]:
    from app.core.jobs.registry import job_registry

    snapshot = dict(job_registry._jobs)
    yield
    job_registry._jobs.clear()
    job_registry._jobs.update(snapshot)
