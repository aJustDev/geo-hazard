"""provincia de cada evento

Cada evento guarda la provincia INE a la que pertenece (province_code),
calculada al escribirlo con la regla de las areas vigiladas (ADR-0021,
ADR-0023): un punto es de la provincia en la que cae; un poligono, de la
provincia con la que mas solapa (las zonas AEMET cruzan limites y las
costeras son sobre todo mar). Fuera de las 52 provincias (mar, Portugal,
norte de Africa) queda NULL.

Calcularlo al vuelo cuesta ~2 ms por poligono (4 s el historico de Murcia
en prod el 2026-11-03); guardado, el filtro por provincia es un indice y el
plano analitico lo lee del GeoParquet sin repetir la geometria.

Lo rellena un trigger BEFORE INSERT OR UPDATE OF geom: el upsert de los
sync siempre reescribe geom y nunca province_code, y la API vieja sigue
insertando mientras corre esta migracion. Un fallo de geometria no debe
tumbar la ingesta: la funcion devuelve NULL y avisa.

Revision ID: dd39f1bfc9f5
Revises: 0daefaeba006
Create Date: 2026-11-03 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "dd39f1bfc9f5"
down_revision: str | None = "0daefaeba006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_INDEX = "ix_hazard_events_province_starts_at"
_BATCH = 5000

_PROVINCE_OF = """
CREATE OR REPLACE FUNCTION hazard_event_province(g geometry) RETURNS varchar(2)
LANGUAGE plpgsql STABLE AS $$
BEGIN
  RETURN (
    SELECT p.code FROM provinces p
    WHERE ST_Intersects(p.geom, g)
    ORDER BY CASE WHEN ST_Dimension(g) = 0 THEN 0
                  ELSE ST_Area(ST_Intersection(p.geom, g)) END DESC,
             p.code
    LIMIT 1
  );
EXCEPTION WHEN OTHERS THEN
  RAISE WARNING 'hazard_event_province: %', SQLERRM;
  RETURN NULL;
END
$$;
"""

_SET_PROVINCE = """
CREATE OR REPLACE FUNCTION hazard_events_set_province() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  NEW.province_code := hazard_event_province(NEW.geom);
  RETURN NEW;
END
$$;
"""


def upgrade() -> None:
    # Tabla viva: lock_timeout propio frente a los 5 s globales de prod.
    op.execute("SET LOCAL lock_timeout = '60s'")
    op.add_column("hazard_events", sa.Column("province_code", sa.String(2), nullable=True))
    op.execute(_PROVINCE_OF)
    op.execute(_SET_PROVINCE)
    op.execute(
        "CREATE TRIGGER hazard_events_province BEFORE INSERT OR UPDATE OF geom "
        "ON hazard_events FOR EACH ROW EXECUTE FUNCTION hazard_events_set_province()"
    )
    # Relleno por lotes, cada uno en su transaccion: los sync pueden escribir
    # a la vez (el trigger ya cubre lo nuevo) y un lote largo bloquearia filas.
    with op.get_context().autocommit_block():
        bind = op.get_bind()
        last = "00000000-0000-0000-0000-000000000000"
        while True:
            row = bind.execute(
                sa.text(
                    "WITH batch AS ("
                    "  SELECT id FROM hazard_events WHERE id > CAST(:last AS uuid)"
                    "  ORDER BY id LIMIT :n"
                    "), done AS ("
                    "  UPDATE hazard_events e SET province_code = hazard_event_province(e.geom)"
                    "  FROM batch WHERE e.id = batch.id RETURNING e.id"
                    ") SELECT id::text FROM done ORDER BY id DESC LIMIT 1"
                ),
                {"last": last, "n": _BATCH},
            ).scalar()
            if row is None:
                break
            last = row
        op.execute("SET lock_timeout = '60s'")
        op.drop_index(
            _INDEX, table_name="hazard_events", postgresql_concurrently=True, if_exists=True
        )
        op.create_index(
            _INDEX,
            "hazard_events",
            ["province_code", sa.text("starts_at DESC"), sa.text("id DESC")],
            postgresql_concurrently=True,
            postgresql_where=sa.text("province_code IS NOT NULL"),
        )
        op.execute("RESET lock_timeout")


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.drop_index(
            _INDEX, table_name="hazard_events", postgresql_concurrently=True, if_exists=True
        )
    op.execute("DROP TRIGGER IF EXISTS hazard_events_province ON hazard_events")
    op.execute("DROP FUNCTION IF EXISTS hazard_events_set_province()")
    op.execute("DROP FUNCTION IF EXISTS hazard_event_province(geometry)")
    op.drop_column("hazard_events", "province_code")
