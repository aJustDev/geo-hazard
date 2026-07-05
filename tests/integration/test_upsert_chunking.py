"""asyncpg limita cada sentencia a 32767 argumentos: el primer sync real de
EFFIS en produccion (~8k hotspots x 9 columnas) lo supero y tumbo el job.
El repo trocea el lote; este test lo fija con un lote que SIN troceo no
cabe en una sola sentencia."""

from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.hazards.models.hazard_event import HazardEventORM
from app.hazards.repos.hazard_event import HazardEventRepo
from app.hazards.services.content_hash import content_hash
from app.hazards.services.geometry import geojson_to_wkb

pytestmark = [pytest.mark.integration, pytest.mark.asyncio(loop_scope="session")]

BASE = datetime(2026, 7, 4, 12, 0, tzinfo=UTC)


def _row(i: int, version: int = 1) -> dict[str, Any]:
    return {
        "source": "effis",
        "hazard_type": "wildfire",
        "external_id": f"hs-{i}",
        "geom": geojson_to_wkb({"type": "Point", "coordinates": [-3.7 + i * 1e-4, 40.4]}),
        "severity": 2,
        "starts_at": BASE,
        "ends_at": None,
        "attrs": {"i": i, "v": version},
        "content_hash": content_hash({"id": i, "v": version}),
    }


async def test_lote_mayor_que_el_limite_de_argumentos_de_asyncpg(
    db_session: AsyncSession,
) -> None:
    # 4001 filas x 9 columnas = 36009 argumentos: reproduce el lote real de
    # hotspots en temporada de incendios que revento el primer sync.
    rows = [_row(i) for i in range(4001)]
    repo = HazardEventRepo(db_session)

    assert await repo.upsert_batch(rows) == (4001, 0)

    # Re-servido identico: no-op completo tambien a traves de los trozos.
    assert await repo.upsert_batch(rows) == (0, 0)

    # Cambios reales repartidos en trozos distintos: solo esos actualizan y
    # los contadores se acumulan entre sentencias.
    for i in (0, 1500, 4000):
        rows[i] = _row(i, version=2)
    assert await repo.upsert_batch(rows) == (0, 3)


async def test_clave_duplicada_en_el_lote_gana_la_ultima_ocurrencia(
    db_session: AsyncSession,
) -> None:
    # EFFIS puede re-servir el mismo fire_id dos veces en una respuesta; sin
    # dedup, dos filas con igual (source, external_id) en una sentencia
    # abortan el ON CONFLICT DO UPDATE entero con CardinalityViolation
    # ("cannot affect row a second time") y el sync devuelve un 500.
    repo = HazardEventRepo(db_session)

    assert await repo.upsert_batch([_row(7, version=1), _row(7, version=2)]) == (1, 0)

    stored = (
        await db_session.execute(
            select(HazardEventORM).where(
                HazardEventORM.source == "effis", HazardEventORM.external_id == "hs-7"
            )
        )
    ).scalar_one()
    assert stored.attrs["v"] == 2
