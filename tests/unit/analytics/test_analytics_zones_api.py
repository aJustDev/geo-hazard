"""Contrato HTTP de /v1/analytics/zone/monthly y /provinces/summary: sin
snapshots responden ceros (no error), y la zona se valida en la frontera."""

from pathlib import Path

import httpx
import pytest

from app.core import config
from app.main import app


@pytest.fixture
async def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(config.settings, "DATA_DIR", str(tmp_path))
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        yield http


async def test_serie_de_una_provincia_sin_datos(client: httpx.AsyncClient) -> None:
    response = await client.get(
        "/v1/analytics/zone/monthly", params={"year": 2026, "province": "30"}
    )
    body = response.json()

    assert response.status_code == 200
    assert body["zone"]["province"] == "30"
    assert body["history_since"] is None
    assert [row["month"] for row in body["rows"]] == list(range(1, 13))
    assert {a["source"] for a in body["attribution"]} == {"aemet", "ign", "effis", "cnig"}


async def test_circulo_sin_cnig_en_la_atribucion(client: httpx.AsyncClient) -> None:
    response = await client.get(
        "/v1/analytics/zone/monthly",
        params={"year": 2026, "lon": -6.67, "lat": 42.27, "radius_m": 160_000},
    )

    assert response.status_code == 200
    assert "cnig" not in {a["source"] for a in response.json()["attribution"]}


@pytest.mark.parametrize(
    ("params", "status"),
    [
        ({"year": 2026}, 400),
        ({"year": 2026, "province": "30", "lon": -1, "lat": 38, "radius_m": 1000}, 400),
        ({"year": 2026, "lon": -1, "lat": 38}, 400),
        ({"year": 2026, "lon": -1, "lat": 38, "radius_m": 300_000}, 422),
        ({"year": 2026, "province": "3"}, 422),
    ],
)
async def test_zona_invalida(client: httpx.AsyncClient, params: dict, status: int) -> None:
    response = await client.get("/v1/analytics/zone/monthly", params=params)

    assert response.status_code == status


async def test_resumen_por_provincia(client: httpx.AsyncClient) -> None:
    response = await client.get("/v1/analytics/provinces/summary", params={"year": 2026})
    rows = response.json()["rows"]

    assert response.status_code == 200
    assert len(rows) == 52
    assert rows[0]["province_code"] == "01"
