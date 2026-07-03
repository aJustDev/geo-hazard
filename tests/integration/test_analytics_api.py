"""La demo de la frontera de planos: el mismo dato, respondido por ambos.

Ingesta EFFIS (fake) -> PostGIS responde la suma operacional; el handler de
export escribe el snapshot GeoParquet -> DuckDB responde el agregado
analitico via HTTP. Los dos numeros DEBEN coincidir: no hay copia manual,
solo el pipeline real de un plano al otro.
"""

from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
from sqlalchemy import Float, func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core import config
from app.core.effis.drivers.fake import EffisFakeClient
from app.core.events.bus import EventBus
from app.hazards.event_handlers import export_geoparquet as export_module
from app.hazards.models.hazard_event import HazardEventORM
from app.hazards.repos.hazard_event import HazardEventRepo
from app.hazards.repos.sync_state import SourceSyncStateRepo
from app.hazards.use_cases.sync_effis import SyncEffisUseCase
from app.main import app

pytestmark = [pytest.mark.integration, pytest.mark.asyncio(loop_scope="session")]


@pytest.fixture
async def analytics_client(
    committing_factory: async_sessionmaker,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> AsyncIterator[tuple[httpx.AsyncClient, async_sessionmaker]]:
    monkeypatch.setattr(config.settings, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(export_module, "async_session_factory", committing_factory)
    (tmp_path / "exports").mkdir()

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client, committing_factory


async def test_ambos_planos_responden_el_mismo_dato(
    analytics_client: tuple[httpx.AsyncClient, async_sessionmaker],
) -> None:
    client, factory = analytics_client

    # 1. Ingesta operacional: el fake trae un area quemada de 820 ha en
    #    Badajoz (y un hotspot, que no aporta hectareas).
    async with factory() as session:
        use_case = SyncEffisUseCase(
            repo=HazardEventRepo(session),
            sync_state=SourceSyncStateRepo(session),
            event_bus=EventBus(session),
        )
        await use_case.execute(client=EffisFakeClient())
        await session.commit()

    # 2. Plano operacional: la suma directa en PostGIS.
    async with factory() as session:
        stmt = select(func.sum(HazardEventORM.attrs["area_ha"].astext.cast(Float))).where(
            HazardEventORM.source == "effis",
            HazardEventORM.attrs["kind"].astext == "burnt_area",
        )
        operational_total = (await session.execute(stmt)).scalar()

    # 3. El puente entre planos: el handler del outbox escribe el snapshot.
    await export_module.export_geoparquet({"source": "effis"})

    # 4. Plano analitico: DuckDB agrega el GeoParquet via HTTP.
    response = await client.get("/v1/analytics/wildfires/burned-area", params={"year": 2026})
    body = response.json()

    assert response.status_code == 200
    analytical_total = sum(row["burned_area_ha"] for row in body["rows"])
    assert operational_total == analytical_total == 820.0
    assert body["rows"][0]["province"] == "Badajoz"
    assert body["rows"][0]["month"] == 7
    assert body["rows"][0]["events"] == 1


async def test_sin_snapshot_el_plano_analitico_responde_vacio(
    analytics_client: tuple[httpx.AsyncClient, async_sessionmaker],
) -> None:
    client, _ = analytics_client

    response = await client.get("/v1/analytics/earthquakes/frequency", params={"year": 2026})

    assert response.status_code == 200
    assert response.json() == {"year": 2026, "min_magnitude": None, "rows": []}


async def test_parametros_invalidos_422(
    analytics_client: tuple[httpx.AsyncClient, async_sessionmaker],
) -> None:
    client, _ = analytics_client

    bad_province = await client.get(
        "/v1/analytics/wildfires/burned-area", params={"year": 2026, "province": "6"}
    )
    bad_phenomenon = await client.get(
        "/v1/analytics/warnings/summary", params={"year": 2026, "phenomenon": "at"}
    )

    assert bad_province.status_code == 422
    assert bad_phenomenon.status_code == 422
