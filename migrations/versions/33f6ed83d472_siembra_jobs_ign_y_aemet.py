"""siembra jobs ign y aemet

Fase IGN+AEMET: solo siembra de scheduled_jobs, sin cambios de esquema (las
dos fuentes reutilizan hazard_events y source_sync_state, ADR-0004).
Intervalos: ign_sync 900s (feed barato y sin auth; latencia baja para
sismos) y aemet_sync 1800s (boletines pocas veces al dia y API con cuota).

Revision ID: 33f6ed83d472
Revises: 4a7755cba66d
Create Date: 2026-07-03 09:27:29.768244

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "33f6ed83d472"
down_revision: str | None = "4a7755cba66d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "INSERT INTO scheduled_jobs (job_name, description, interval_seconds, next_run_at, status) "
        "VALUES ('ign_sync', 'Sincroniza el catalogo sismico IGN (GeoRSS, ventana de 10 dias) y "
        "publica hazards.batch_ingested.', 900, now(), 'PENDING') "
        "ON CONFLICT (job_name) DO NOTHING"
    )
    op.execute(
        "INSERT INTO scheduled_jobs (job_name, description, interval_seconds, next_run_at, status) "
        "VALUES ('aemet_sync', 'Sincroniza los avisos CAP de AEMET Meteoalerta y "
        "publica hazards.batch_ingested.', 1800, now(), 'PENDING') "
        "ON CONFLICT (job_name) DO NOTHING"
    )


def downgrade() -> None:
    op.execute("DELETE FROM scheduled_jobs WHERE job_name IN ('ign_sync', 'aemet_sync')")
