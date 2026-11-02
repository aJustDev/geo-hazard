"""indices de lote por fuente

Los avisos (ADR-0021) seleccionan las filas de un lote por la marca de
tiempo de su transaccion: source = :s AND (created_at = :t OR updated_at =
:t). Dos indices para que eso sea un BitmapOr y no un scan de la fuente.

hazard_events esta viva durante el deploy (la API vieja sigue sincronizando
mientras corre la migracion), asi que se construyen CONCURRENTLY, fuera de
la transaccion y con un lock_timeout propio: el global de prod es 5 s. Un
build concurrente fallido deja un indice INVALID que IF NOT EXISTS daria
por bueno, de ahi el DROP previo.

Revision ID: 9c41e2d7a6b3
Revises: 04ddf0041d06
Create Date: 2026-11-02 18:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "9c41e2d7a6b3"
down_revision: str | None = "04ddf0041d06"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_INDEXES = (
    ("ix_hazard_events_source_created_at", "created_at"),
    ("ix_hazard_events_source_updated_at", "updated_at"),
)


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("SET lock_timeout = '60s'")
        for name, column in _INDEXES:
            op.drop_index(
                name, table_name="hazard_events", postgresql_concurrently=True, if_exists=True
            )
            op.create_index(name, "hazard_events", ["source", column], postgresql_concurrently=True)
        op.execute("RESET lock_timeout")


def downgrade() -> None:
    with op.get_context().autocommit_block():
        for name, _column in _INDEXES:
            op.drop_index(
                name, table_name="hazard_events", postgresql_concurrently=True, if_exists=True
            )
