from app.core.jobs.registry import JobRegistry


def test_register_and_get() -> None:
    registry = JobRegistry()

    @registry.register("demo")
    async def _demo() -> None:
        return None

    assert registry.get("demo") is _demo
    assert "demo" in registry.registered_jobs
    assert registry.get("missing") is None
