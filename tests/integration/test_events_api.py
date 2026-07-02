"""Contrato HTTP de /v1/events contra PostGIS real: GeoJSON, filtros bbox y
paginacion keyset."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.db import get_session
from app.hazards.models.hazard_event import HazardEventORM
from app.hazards.services.content_hash import content_hash
from app.hazards.services.geometry import geojson_to_wkb
from app.main import app

pytestmark = [pytest.mark.integration, pytest.mark.asyncio(loop_scope="session")]

BASE = datetime(2026, 7, 1, 12, 0, tzinfo=UTC)


def _event(i: int, *, lon: float, lat: float) -> HazardEventORM:
    geometry = {"type": "Point", "coordinates": [lon, lat]}
    return HazardEventORM(
        source="effis",
        hazard_type="wildfire",
        external_id=f"api-test-{i}",
        geom=geojson_to_wkb(geometry),
        severity=2,
        starts_at=BASE + timedelta(hours=i),
        ends_at=None,
        attrs={"kind": "hotspot"},
        content_hash=content_hash({"i": i}),
    )


@pytest.fixture
async def seeded_client(
    committing_factory: async_sessionmaker,
) -> AsyncIterator[httpx.AsyncClient]:
    # 3 puntos en la peninsula y 1 en Canarias (fuera del bbox peninsular).
    async with committing_factory() as session:
        session.add_all(
            [
                _event(0, lon=-5.1, lat=39.2),
                _event(1, lon=-3.7, lat=40.4),
                _event(2, lon=2.2, lat=41.4),
                _event(3, lon=-15.6, lat=27.9),
            ]
        )
        await session.commit()

    async def _override() -> AsyncIterator[AsyncSession]:
        async with committing_factory() as session:
            yield session

    app.dependency_overrides[get_session] = _override
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
    app.dependency_overrides.clear()


async def test_bbox_peninsular_excluye_canarias(seeded_client: httpx.AsyncClient) -> None:
    response = await seeded_client.get("/v1/events", params={"bbox": "-9.5,36.0,3.4,43.8"})
    body = response.json()
    assert response.status_code == 200
    assert body["type"] == "FeatureCollection"
    assert body["numberReturned"] == 3
    ids = {f["properties"]["external_id"] for f in body["features"]}
    assert ids == {"api-test-0", "api-test-1", "api-test-2"}
    # Geometria GeoJSON con ejes lon, lat.
    assert body["features"][0]["geometry"]["type"] == "Point"


async def test_paginacion_keyset_recorre_todo_sin_duplicados(
    seeded_client: httpx.AsyncClient,
) -> None:
    seen: list[str] = []
    cursor: str | None = None
    for _ in range(10):
        params: dict[str, str | int] = {"limit": 2}
        if cursor:
            params["cursor"] = cursor
        body = (await seeded_client.get("/v1/events", params=params)).json()
        seen.extend(f["properties"]["external_id"] for f in body["features"])
        cursor = body["nextCursor"]
        if cursor is None:
            break

    assert len(seen) == 4
    assert len(set(seen)) == 4
    # Orden estable: starts_at DESC (el 3 es el mas reciente).
    assert seen[0] == "api-test-3"


async def test_bbox_invalida_400(seeded_client: httpx.AsyncClient) -> None:
    response = await seeded_client.get("/v1/events", params={"bbox": "3.4,36.0,-9.5,43.8"})
    assert response.status_code == 400
    assert response.json()["code"] == "business_validation"


async def test_cursor_corrupto_400(seeded_client: httpx.AsyncClient) -> None:
    response = await seeded_client.get("/v1/events", params={"cursor": "garbage"})
    assert response.status_code == 400


async def test_get_por_id_y_404(seeded_client: httpx.AsyncClient) -> None:
    collection = (await seeded_client.get("/v1/events", params={"limit": 1})).json()
    event_id = collection["features"][0]["id"]

    response = await seeded_client.get(f"/v1/events/{event_id}")
    assert response.status_code == 200
    assert response.json()["id"] == event_id

    missing = await seeded_client.get("/v1/events/00000000-0000-0000-0000-000000000000")
    assert missing.status_code == 404
    assert missing.json()["code"] == "not_found"
