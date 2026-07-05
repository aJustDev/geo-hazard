"""indice de soporte del cursor keyset

El orden global de /v1/events es (starts_at DESC, id DESC) y el cursor
filtra por esa tupla, pero el unico indice con starts_at lo prefija
hazard_type: la lista SIN filtro de tipo (el caso comun) pagaba un sort
completo en cada pagina. Indice dedicado para que el keyset sea un scan.

Revision ID: 04ddf0041d06
Revises: b7e3d1a9c204
Create Date: 2026-07-05 14:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "04ddf0041d06"
down_revision: str | None = "b7e3d1a9c204"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_hazard_events_starts_at_id",
        "hazard_events",
        [sa.text("starts_at DESC"), sa.text("id DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_hazard_events_starts_at_id", table_name="hazard_events")
