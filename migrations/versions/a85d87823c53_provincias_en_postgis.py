"""provincias en postgis

Las areas vigiladas de los avisos (ADR-0021) se casan en Postgres, asi que
las provincias INE pasan a una tabla sembrada desde el mismo
data/reference/provinces_es.parquet que lee el plano analitico (ADR-0013):
una sola fuente de verdad. inner_geom es la provincia encogida 1 km con un
buffer geography (exacto tambien en Canarias); si una parte desaparece se
queda la geometria completa. Cambiar el margen es una migracion nueva.

Tabla nueva y vacia: no aplican las reglas DDL sin-downtime.

Revision ID: a85d87823c53
Revises: 9c41e2d7a6b3
Create Date: 2026-11-02 19:00:00.000000

"""

from collections.abc import Sequence
from pathlib import Path

import pyarrow.parquet as pq
import sqlalchemy as sa
from alembic import op
from geoalchemy2 import Geometry

# revision identifiers, used by Alembic.
revision: str = "a85d87823c53"
down_revision: str | None = "9c41e2d7a6b3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PARQUET = Path(__file__).resolve().parents[2] / "data" / "reference" / "provinces_es.parquet"
# 50 provincias + Ceuta y Melilla (ADR-0013).
_EXPECTED_ROWS = 52
_INNER_MARGIN_M = 1000

# Mezcla Polygon y MultiPolygon: todo a MultiPolygon valido. inner_geom
# vacio (una isla mas estrecha que 2 km) cae a la geometria completa.
_INSERT = sa.text(
    """
    INSERT INTO provinces (code, name, geom, inner_geom)
    SELECT CAST(:code AS varchar), CAST(:name AS varchar), g,
           CASE WHEN ST_IsEmpty(i) THEN g ELSE i END
    FROM (
        SELECT g, ST_Multi(ST_CollectionExtract(ST_MakeValid(
                   ST_Buffer(g::geography, -CAST(:margin AS float8))::geometry), 3)) AS i
        FROM (SELECT ST_Multi(ST_CollectionExtract(ST_MakeValid(
                     ST_GeomFromWKB(CAST(:wkb AS bytea), 4326)), 3)) AS g) AS raw
    ) AS buffered
    """
)


def _geometry_column(name: str) -> sa.Column:
    return sa.Column(
        name,
        Geometry(
            geometry_type="MULTIPOLYGON",
            srid=4326,
            dimension=2,
            spatial_index=False,
            from_text="ST_GeomFromEWKT",
            name="geometry",
            nullable=False,
        ),
        nullable=False,
    )


def upgrade() -> None:
    if op.get_context().as_sql:
        raise RuntimeError("provinces se siembra leyendo un parquet: no hay modo offline")

    op.create_geospatial_table(
        "provinces",
        sa.Column("code", sa.String(length=2), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        _geometry_column("geom"),
        _geometry_column("inner_geom"),
        sa.CheckConstraint("code ~ '^[0-9]{2}$'", name=op.f("ck_provinces_codigo_ine")),
        sa.PrimaryKeyConstraint("code", name=op.f("pk_provinces")),
    )
    for column in ("geom", "inner_geom"):
        op.create_geospatial_index(
            f"idx_provinces_{column}",
            "provinces",
            [column],
            unique=False,
            postgresql_using="gist",
            postgresql_ops={},
        )

    table = pq.read_table(_PARQUET, columns=["province_code", "name", "geom"])
    bind = op.get_bind()
    for row in table.to_pylist():
        bind.execute(
            _INSERT,
            {
                "code": row["province_code"],
                "name": row["name"],
                "wkb": row["geom"],
                "margin": _INNER_MARGIN_M,
            },
        )
    seeded = bind.execute(sa.text("SELECT count(*) FROM provinces")).scalar_one()
    if seeded != _EXPECTED_ROWS:
        raise RuntimeError(f"provinces: {seeded} filas sembradas, se esperaban {_EXPECTED_ROWS}")


def downgrade() -> None:
    op.drop_geospatial_index(
        "idx_provinces_inner_geom", table_name="provinces", column_name="inner_geom"
    )
    op.drop_geospatial_index("idx_provinces_geom", table_name="provinces", column_name="geom")
    op.drop_geospatial_table("provinces")
