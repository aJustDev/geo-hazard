"""siembra job notifications_deliver

Entrega de los avisos pendientes cada 60 s (ADR-0021). Sin suscripciones no
hace nada mas que una consulta vacia.

Revision ID: 0daefaeba006
Revises: 06d486394872
Create Date: 2026-11-02 21:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0daefaeba006"
down_revision: str | None = "06d486394872"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "INSERT INTO scheduled_jobs (job_name, description, interval_seconds, next_run_at, status) "
        "VALUES ('notifications_deliver', 'Entrega los avisos pendientes por ntfy o webhook', "
        "60, now(), 'PENDING') "
        "ON CONFLICT (job_name) DO NOTHING"
    )


def downgrade() -> None:
    op.execute("DELETE FROM scheduled_jobs WHERE job_name = 'notifications_deliver'")
