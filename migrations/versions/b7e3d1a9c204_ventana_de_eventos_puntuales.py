"""ventana de eventos puntuales

ADR-0016: sismos y detecciones satelitales (hotspots) son eventos
puntuales; su ventana de vigencia es su propio instante. Backfill de las
filas ya ingeridas con ends_at NULL para que el filtro `active` no las
trate como abiertas. Las areas quemadas NRT se quedan como estan: abiertas
(NULL) mientras la capa las sirva; las cierra el sync por desaparicion.

Revision ID: b7e3d1a9c204
Revises: 33f6ed83d472
Create Date: 2026-07-04 23:20:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b7e3d1a9c204"
down_revision: str | None = "33f6ed83d472"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "UPDATE hazard_events SET ends_at = starts_at WHERE source = 'ign' AND ends_at IS NULL"
    )
    op.execute(
        "UPDATE hazard_events SET ends_at = starts_at "
        "WHERE source = 'effis' AND attrs->>'kind' = 'hotspot' AND ends_at IS NULL"
    )


def downgrade() -> None:
    # Reversible sin perdida: para estos dos casos ends_at era NULL y el
    # valor nuevo (= starts_at) es derivable.
    op.execute(
        "UPDATE hazard_events SET ends_at = NULL WHERE source = 'ign' AND ends_at = starts_at"
    )
    op.execute(
        "UPDATE hazard_events SET ends_at = NULL "
        "WHERE source = 'effis' AND attrs->>'kind' = 'hotspot' AND ends_at = starts_at"
    )
