"""Guarda de concurrencia del plano analitico (G2, ADR-0017).

Con un solo slot ocupado por una query en vuelo, la siguiente no se encola
indefinidamente: se rechaza con ServiceOverloadedError (503) tras el timeout
corto de adquisicion.
"""

import threading

import anyio
import pytest

from app.analytics import concurrency
from app.core.exceptions.exceptions import ServiceOverloadedError


def _fast() -> str:
    return "done"


async def test_plano_saturado_rechaza_con_503(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(concurrency._limiter, "total_tokens", 1)
    monkeypatch.setattr(concurrency.settings, "ANALYTICS_ACQUIRE_TIMEOUT_SECONDS", 0.05)

    started = threading.Event()
    release = threading.Event()

    def _slow() -> str:
        # Sincrono, corre en el threadpool via run_blocking: retiene el unico
        # slot hasta que el test lo suelta (sin sleeps que dependan de la carga).
        started.set()
        release.wait(timeout=5)
        return "done"

    async with anyio.create_task_group() as tg:
        tg.start_soon(concurrency.run_analytics, _slow)
        while not started.is_set():
            await anyio.sleep(0.005)

        try:
            with pytest.raises(ServiceOverloadedError) as excinfo:
                await concurrency.run_analytics(_fast)
        finally:
            release.set()

    assert excinfo.value.status_code == 503
    assert excinfo.value.retry_after == 1


async def test_slot_se_libera_tras_la_query(monkeypatch: pytest.MonkeyPatch) -> None:
    # Con un slot, dos llamadas SECUENCIALES pasan: el slot se libera al acabar.
    monkeypatch.setattr(concurrency._limiter, "total_tokens", 1)
    monkeypatch.setattr(concurrency.settings, "ANALYTICS_ACQUIRE_TIMEOUT_SECONDS", 0.05)

    assert await concurrency.run_analytics(_fast) == "done"
    assert await concurrency.run_analytics(_fast) == "done"
