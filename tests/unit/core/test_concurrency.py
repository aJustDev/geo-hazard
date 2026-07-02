import threading

from app.core.concurrency import run_blocking


async def test_run_blocking_returns_result_and_passes_args() -> None:
    def add(a: int, b: int, *, c: int) -> int:
        return a + b + c

    assert await run_blocking(add, 1, 2, c=3) == 6


async def test_run_blocking_runs_off_the_event_loop_thread() -> None:
    def current_thread() -> int:
        return threading.get_ident()

    worker_thread = await run_blocking(current_thread)
    assert worker_thread != threading.get_ident()
