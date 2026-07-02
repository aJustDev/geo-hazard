from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from app.api.v1 import health as health_module
from app.main import app


def make_client() -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


async def test_readiness_503_si_no_ready() -> None:
    app.state.ready = False
    async with make_client() as client:
        response = await client.get("/v1/health/readiness")
    assert response.status_code == 503
    assert response.json() == {"status": "not ready"}


async def test_readiness_503_si_db_caida(monkeypatch: pytest.MonkeyPatch) -> None:
    app.state.ready = True
    engine = MagicMock()
    engine.connect.side_effect = ConnectionError("boom")
    monkeypatch.setattr(health_module, "engine", engine)

    async with make_client() as client:
        response = await client.get("/v1/health/readiness")
    assert response.status_code == 503
    assert response.json() == {"status": "database unavailable"}


async def test_readiness_200_si_todo_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    app.state.ready = True
    engine = MagicMock()
    engine.connect.return_value = AsyncMock()
    monkeypatch.setattr(health_module, "engine", engine)

    async with make_client() as client:
        response = await client.get("/v1/health/readiness")
    assert response.status_code == 200
    assert response.json() == {"status": "ready"}
