"""Siembra de provincias en PostGIS (ADR-0021): 52 filas validas y cada punto
de referencia cae en su provincia."""

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.hazards.models import ProvinceORM

pytestmark = [pytest.mark.integration, pytest.mark.asyncio(loop_scope="session")]


async def test_52_provincias_validas_y_multipoligono(db_session: AsyncSession) -> None:
    rows = (
        await db_session.execute(
            select(
                func.count(),
                func.count().filter(func.ST_IsValid(ProvinceORM.geom)),
                func.count().filter(func.GeometryType(ProvinceORM.geom) != "MULTIPOLYGON"),
            )
        )
    ).one()
    total, geom_ok, not_multi = rows
    assert total == 52
    assert geom_ok == 52
    assert not_multi == 0


@pytest.mark.parametrize(
    ("lon", "lat", "code"),
    [
        (-1.1307, 37.9922, "30"),  # Murcia
        (-3.7038, 40.4168, "28"),  # Madrid
        # Interior de Gran Canaria: la costa simplificada (ADR-0013) deja la
        # capital a ~500 m fuera del poligono.
        (-15.6, 27.95, "35"),
        (-16.2519, 28.4636, "38"),  # Santa Cruz de Tenerife
        (2.6502, 39.5696, "07"),  # Palma
        (-5.3162, 35.8894, "51"),  # Ceuta
        (-2.9381, 35.2923, "52"),  # Melilla
    ],
)
async def test_punto_cae_en_su_provincia(
    db_session: AsyncSession, lon: float, lat: float, code: str
) -> None:
    point = func.ST_SetSRID(func.ST_MakePoint(lon, lat), 4326)
    found = (
        (
            await db_session.execute(
                select(ProvinceORM.code).where(func.ST_Intersects(ProvinceORM.geom, point))
            )
        )
        .scalars()
        .all()
    )
    assert found == [code]
