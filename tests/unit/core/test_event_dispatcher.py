from typing import Any

from app.core.events.dispatcher import EventDispatcher


async def test_dispatch_runs_handlers_and_reports_success() -> None:
    dispatcher = EventDispatcher()
    calls: list[dict[str, Any]] = []

    @dispatcher.register("evt")
    async def _ok(payload: dict[str, Any]) -> None:
        calls.append(payload)

    result = await dispatcher.dispatch("evt", {"x": 1})

    assert result.all_succeeded
    assert calls == [{"x": 1}]


async def test_dispatch_isolates_failures() -> None:
    dispatcher = EventDispatcher()

    @dispatcher.register("evt")
    async def _boom(payload: dict[str, Any]) -> None:
        raise RuntimeError("nope")

    result = await dispatcher.dispatch("evt", {})

    assert not result.all_succeeded
    assert "nope" in result.errors_summary


async def test_dispatch_skips_completed_handlers() -> None:
    dispatcher = EventDispatcher()
    calls: list[int] = []

    @dispatcher.register("evt")
    async def _h(payload: dict[str, Any]) -> None:
        calls.append(1)

    result = await dispatcher.dispatch("evt", {}, completed_handlers={"_h"})

    assert result.all_succeeded
    assert calls == []


async def test_dispatch_no_handlers_is_vacuously_succeeded() -> None:
    dispatcher = EventDispatcher()
    result = await dispatcher.dispatch("unknown", {})
    assert result.all_succeeded
