"""Contrato HTTP de /v1/events/near y /v1/events/clusters contra PostGIS real.

La geografia del seed esta elegida para que las distancias sean verificables
de cabeza: un trio apretado alrededor de Madrid (~4 km entre si), un punto
en Toledo (~67 km) y otro en Barcelona (~500 km).
"""

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.db import get_session
from app.hazards.models.hazard_event import HazardEventORM
from app.hazards.repos.hazard_event import HazardEventRepo
from app.hazards.services.content_hash import content_hash
from app.hazards.services.geometry import geojson_to_wkb
from app.main import app

pytestmark = [pytest.mark.integration, pytest.mark.asyncio(loop_scope="session")]

BASE = datetime(2026, 7, 1, 12, 0, tzinfo=UTC)

# Centro de consulta: el primer punto del trio de Madrid.
MADRID = {"lon": -3.70, "lat": 40.42}

# Bbox peninsular que cubre todo el seed (Madrid, Toledo, BCN): satisface la
# cota obligatoria de /clusters sin alterar que puntos entran (ADR-0017).
IBERIA_BBOX = "-9.5,36.0,3.4,43.8"


def _event(
    external_id: str,
    *,
    lon: float,
    lat: float,
    hazard_type: str = "wildfire",
    source: str = "effis",
    severity: int = 2,
    hours: int = 0,
) -> HazardEventORM:
    return HazardEventORM(
        source=source,
        hazard_type=hazard_type,
        external_id=external_id,
        geom=geojson_to_wkb({"type": "Point", "coordinates": [lon, lat]}),
        severity=severity,
        starts_at=BASE + timedelta(hours=hours),
        ends_at=None,
        attrs={},
        content_hash=content_hash({"id": external_id}),
    )


@pytest.fixture
async def seeded_client(
    committing_factory: async_sessionmaker,
) -> AsyncIterator[httpx.AsyncClient]:
    async with committing_factory() as session:
        session.add_all(
            [
                _event("near-m0", lon=-3.70, lat=40.42),
                _event("near-m1", lon=-3.75, lat=40.42, severity=3, hours=1),
                _event("near-m2", lon=-3.70, lat=40.46, hours=2),
                # Un sismo pegado al trio: para demostrar los filtros.
                _event(
                    "near-q", lon=-3.71, lat=40.43, hazard_type="earthquake", source="ign", hours=3
                ),
                _event("near-toledo", lon=-4.02, lat=39.86, hours=4),
                _event("near-bcn", lon=2.15, lat=41.39, hours=5),
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


async def test_near_ordena_por_distancia(seeded_client: httpx.AsyncClient) -> None:
    response = await seeded_client.get("/v1/events/near", params={**MADRID, "radius_m": 10_000})
    body = response.json()

    assert response.status_code == 200
    assert body["numberReturned"] == 4  # el trio + el sismo; Toledo y BCN fuera
    distances = [f["properties"]["distance_m"] for f in body["features"]]
    assert distances == sorted(distances)
    assert distances[0] < 1  # el centro es exactamente near-m0
    assert all(d <= 10_000 for d in distances)
    assert body["features"][0]["properties"]["external_id"] == "near-m0"


async def test_near_distancia_verificable(seeded_client: httpx.AsyncClient) -> None:
    # Madrid -> Toledo son ~67 km; si el calculo cae fuera de esa banda, o
    # los ejes estan invertidos o la proyeccion no es metrica.
    response = await seeded_client.get("/v1/events/near", params={**MADRID, "radius_m": 100_000})
    body = response.json()

    assert body["numberReturned"] == 5
    toledo = body["features"][-1]
    assert toledo["properties"]["external_id"] == "near-toledo"
    assert 60_000 < toledo["properties"]["distance_m"] < 75_000


async def test_near_respeta_los_filtros(seeded_client: httpx.AsyncClient) -> None:
    response = await seeded_client.get(
        "/v1/events/near",
        params={**MADRID, "radius_m": 10_000, "hazard_type": "wildfire"},
    )
    ids = {f["properties"]["external_id"] for f in response.json()["features"]}
    assert ids == {"near-m0", "near-m1", "near-m2"}


async def test_near_radio_maximo_422(seeded_client: httpx.AsyncClient) -> None:
    response = await seeded_client.get("/v1/events/near", params={**MADRID, "radius_m": 250_000})
    assert response.status_code == 422


async def test_clusters_agrupa_y_excluye_ruido(seeded_client: httpx.AsyncClient) -> None:
    response = await seeded_client.get(
        "/v1/events/clusters",
        params={"eps_m": 5_000, "min_points": 3, "hazard_type": "wildfire", "bbox": IBERIA_BBOX},
    )
    body = response.json()

    assert response.status_code == 200
    assert body["numberReturned"] == 1  # Toledo y BCN son ruido, no clusters
    cluster = body["features"][0]
    assert cluster["properties"]["count"] == 3
    assert cluster["properties"]["max_severity"] == 3
    # Centroide metrico del trio, devuelto en 4326.
    lon, lat = cluster["geometry"]["coordinates"]
    assert abs(lon - (-3.7166)) < 0.02
    assert abs(lat - 40.4333) < 0.02


async def test_clusters_sin_filtro_de_tipo_absorbe_al_sismo(
    seeded_client: httpx.AsyncClient,
) -> None:
    response = await seeded_client.get(
        "/v1/events/clusters", params={"eps_m": 5_000, "min_points": 3, "bbox": IBERIA_BBOX}
    )
    body = response.json()

    assert body["numberReturned"] == 1
    assert body["features"][0]["properties"]["count"] == 4


async def test_clusters_min_points_exigente_devuelve_vacio(
    seeded_client: httpx.AsyncClient,
) -> None:
    response = await seeded_client.get(
        "/v1/events/clusters", params={"eps_m": 5_000, "min_points": 6, "bbox": IBERIA_BBOX}
    )
    body = response.json()

    assert body["numberReturned"] == 0
    assert body["features"] == []


async def test_clusters_sin_cota_es_400(seeded_client: httpx.AsyncClient) -> None:
    # C1a (ADR-0017): sin bbox ni starts_after el DBSCAN correria sobre toda
    # la tabla; se rechaza como error de negocio, no se ejecuta.
    response = await seeded_client.get("/v1/events/clusters", params={"eps_m": 5_000})
    assert response.status_code == 400
    assert response.json()["code"] == "business_validation"


async def test_clusters_con_solo_starts_after_basta(seeded_client: httpx.AsyncClient) -> None:
    # Una ventana temporal es cota suficiente: no hace falta bbox.
    response = await seeded_client.get(
        "/v1/events/clusters",
        params={"eps_m": 5_000, "min_points": 3, "starts_after": "2026-01-01T00:00:00Z"},
    )
    assert response.status_code == 200
    assert response.json()["numberReturned"] == 1


async def test_clusters_bbox_malformada_es_400(seeded_client: httpx.AsyncClient) -> None:
    response = await seeded_client.get(
        "/v1/events/clusters", params={"eps_m": 5_000, "bbox": "1,2,3"}
    )
    assert response.status_code == 400
    assert response.json()["code"] == "business_validation"


async def test_clusters_bbox_recorta_espacialmente(seeded_client: httpx.AsyncClient) -> None:
    # Un bbox ajustado a Barcelona (un solo punto) deja al trio de Madrid
    # fuera: sin min_points vecinos, no hay cluster. Prueba que el recorte
    # espacial se aplica ANTES del DBSCAN.
    response = await seeded_client.get(
        "/v1/events/clusters",
        params={"eps_m": 5_000, "min_points": 3, "bbox": "1.9,41.1,2.4,41.6"},
    )
    assert response.status_code == 200
    assert response.json()["numberReturned"] == 0


async def test_near_prefiltra_con_el_gist(db_session: AsyncSession) -> None:
    # El argumento de la fase: el prefiltro en 4326 permite usar el GiST
    # aunque la metrica se calcule en 25830. Con seqscan deshabilitado, el
    # plan DEBE nombrar al indice; si el prefiltro desapareciera, esto
    # degradaria a transformar la tabla entera en cada peticion.
    stmt = HazardEventRepo(db_session)._near_stmt(
        latitude=MADRID["lat"], longitude=MADRID["lon"], radius_m=10_000
    )
    sql = str(stmt.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))

    await db_session.execute(text("SET LOCAL enable_seqscan = off"))
    rows = (await db_session.execute(text(f"EXPLAIN {sql}"))).scalars().all()
    plan = "\n".join(rows)

    assert "idx_hazard_events_geom" in plan
