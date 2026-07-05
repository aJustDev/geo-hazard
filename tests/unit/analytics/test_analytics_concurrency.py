"""Guarda de concurrencia del plano analitico (G2, ADR-0017).

Con un solo slot ocupado por una query en vuelo, la siguiente no se encola
indefinidamente: se rechaza con ServiceOverloadedError (503) tras el timeout
corto de adquisicion.
"""

import time

import anyio
import pytest

from app.analytics import concurrency
from app.core.exceptions.exceptions import ServiceOverloadedError


def _slow() -> str:
    # Sincrono, corre en el threadpool via run_blocking; mantiene el slot.
    time.sleep(0.3)
    return "done"


def _fast() -> str:
    return "done"


async def test_plano_saturado_rechaza_con_503(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(concurrency._limiter, "total_tokens", 1)
    monkeypatch.setattr(concurrency.settings, "ANALYTICS_ACQUIRE_TIMEOUT_SECONDS", 0.05)

    async with anyio.create_task_group() as tg:
        tg.start_soon(concurrency.run_analytics, _slow)
        # Deja que el primero adquiera el unico slot y entre en la query.
        await anyio.sleep(0.1)

        with pytest.raises(ServiceOverloadedError) as excinfo:
            await concurrency.run_analytics(_fast)

    assert excinfo.value.status_code == 503
    assert excinfo.value.retry_after == 1


async def test_slot_se_libera_tras_la_query(monkeypatch: pytest.MonkeyPatch) -> None:
    # Con un slot, dos llamadas SECUENCIALES pasan: el slot se libera al acabar.
    monkeypatch.setattr(concurrency._limiter, "total_tokens", 1)
    monkeypatch.setattr(concurrency.settings, "ANALYTICS_ACQUIRE_TIMEOUT_SECONDS", 0.05)

    assert await concurrency.run_analytics(_fast) == "done"
    assert await concurrency.run_analytics(_fast) == "done"
