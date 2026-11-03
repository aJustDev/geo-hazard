"""Filtro por provincia de /v1/events contra PostGIS real: un punto es de la
provincia en la que cae y un poligono de la provincia con la que mas solapa
(la misma regla que las areas vigiladas, ADR-0021)."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from shapely import wkt
from shapely.geometry import mapping
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.db import get_session
from app.hazards.models.hazard_event import HazardEventORM
from app.hazards.services.content_hash import content_hash
from app.hazards.services.geometry import geojson_to_wkb
from app.main import app

pytestmark = [pytest.mark.integration, pytest.mark.asyncio(loop_scope="session")]

BASE = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)
# Vega del Segura, dentro de Murcia.
VEGA = "POLYGON((-1.3 38.0, -1.0 38.0, -1.0 38.2, -1.3 38.2, -1.3 38.0))"
# Toca Murcia pero solapa sobre todo con Almeria (Valle del Almanzora).
ALMANZORA = "POLYGON((-2.3 37.45, -1.85 37.45, -1.85 37.65, -2.3 37.65, -2.3 37.45))"


def _event(name: str, geometry: str, hours: int, hazard_type: str = "weather_warning"):
    return HazardEventORM(
        source="aemet" if hazard_type == "weather_warning" else "ign",
        hazard_type=hazard_type,
        external_id=name,
        geom=geojson_to_wkb(mapping(wkt.loads(geometry))),
        severity=2,
        starts_at=BASE + timedelta(hours=hours),
        ends_at=None,
        attrs={},
        content_hash=content_hash({"name": name}),
    )


@pytest.fixture
async def client(committing_factory: async_sessionmaker) -> AsyncIterator[httpx.AsyncClient]:
    async with committing_factory() as session:
        session.add_all(
            [
                _event("vega", VEGA, 0),
                _event("almanzora", ALMANZORA, 1),
                # Sismos: Murcia capital, Cartagena y Almeria capital.
                _event("sismo-murcia", "POINT(-1.13 37.98)", 2, "earthquake"),
                _event("sismo-cartagena", "POINT(-0.99 37.62)", 3, "earthquake"),
                _event("sismo-almeria", "POINT(-2.46 36.84)", 4, "earthquake"),
            ]
        )
        await session.commit()

    async def _override() -> AsyncIterator[AsyncSession]:
        async with committing_factory() as session:
            yield session

    app.dependency_overrides[get_session] = _override
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        yield http
    app.dependency_overrides.clear()


def _ids(body: dict) -> set[str]:
    return {f["properties"]["external_id"] for f in body["features"]}


async def test_poligono_de_la_provincia_con_mayor_solape(client: httpx.AsyncClient) -> None:
    murcia = (await client.get("/v1/events", params={"province": "30"})).json()
    almeria = (await client.get("/v1/events", params={"province": "04"})).json()

    assert _ids(murcia) == {"vega", "sismo-murcia", "sismo-cartagena"}
    assert _ids(almeria) == {"almanzora", "sismo-almeria"}
    # La pertenencia sale de los limites del CNIG: se atribuyen.
    assert {a["source"] for a in murcia["attribution"]} == {"aemet", "ign", "cnig"}


async def test_combina_con_otros_filtros_y_con_el_cursor(client: httpx.AsyncClient) -> None:
    seen: list[str] = []
    cursor: str | None = None
    while True:
        params = {"province": "30", "hazard_type": "earthquake", "limit": 1}
        if cursor:
            params["cursor"] = cursor
        body = (await client.get("/v1/events", params=params)).json()
        seen += [f["properties"]["external_id"] for f in body["features"]]
        cursor = body["nextCursor"]
        if not cursor:
            break

    assert seen == ["sismo-cartagena", "sismo-murcia"]


async def test_provincia_sin_eventos_y_codigo_invalido(client: httpx.AsyncClient) -> None:
    empty = await client.get("/v1/events", params={"province": "15"})
    invalid = await client.get("/v1/events", params={"province": "6"})

    assert empty.status_code == 200
    assert empty.json()["features"] == []
    assert invalid.status_code == 422


async def test_trigger_recalcula_al_cambiar_la_geometria_y_deja_null_en_el_mar(
    committing_factory: async_sessionmaker,
) -> None:
    async with committing_factory() as session:
        moving = _event("movil", "POINT(-1.13 37.98)", 5, "earthquake")
        offshore = _event("alboran", "POINT(-3.0 36.0)", 6, "earthquake")
        session.add_all([moving, offshore])
        await session.commit()
        await session.refresh(moving)
        await session.refresh(offshore)
        assert moving.province_code == "30"
        assert offshore.province_code is None

        moving.geom = geojson_to_wkb({"type": "Point", "coordinates": [-2.46, 36.84]})
        await session.commit()
        await session.refresh(moving)
        assert moving.province_code == "04"
