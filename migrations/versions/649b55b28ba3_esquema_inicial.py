"""esquema inicial

Esquema inicial de geo-hazard: extension PostGIS y la infraestructura
Postgres-nativa (scheduled_jobs para el scheduler con lease, outbox_events para
el outbox transaccional, con sus indices parciales). Las tablas de dominio
(hazard_events, source_sync_state) llegan con la primera fuente; los jobs se
siembran en la migracion de cada fuente.

Revision ID: 649b55b28ba3
Revises:
Create Date: 2026-07-02 21:45:29.109459

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "649b55b28ba3"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # PostGIS debe existir antes de que cualquier migracion posterior cree
    # columnas Geometry. El rol de BD necesita privilegio para CREATE EXTENSION
    # (superuser o extension preinstalada, como en la imagen postgis/postgis).
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")

    op.create_table(
        "scheduled_jobs",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("job_name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("interval_seconds", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="PENDING", nullable=False),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "next_run_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("run_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("claimed_by", sa.String(length=255), nullable=True),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_scheduled_jobs")),
        sa.UniqueConstraint("job_name", name=op.f("uq_scheduled_jobs_job_name")),
    )
    # Indice parcial: el poll del worker solo mira filas PENDING vencidas.
    op.create_index(
        "scheduled_jobs_pending_idx",
        "scheduled_jobs",
        ["next_run_at"],
        unique=False,
        postgresql_where=sa.text("status = 'PENDING'"),
    )

    op.create_table(
        "outbox_events",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("aggregate_id", sa.UUID(), nullable=True),
        sa.Column("correlation_id", sa.UUID(), nullable=True),
        sa.Column("event_type", sa.String(length=255), nullable=False),
        sa.Column(
            "payload", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False
        ),
        sa.Column("status", sa.String(length=20), server_default="PENDING", nullable=False),
        sa.Column("retry_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("max_retries", sa.Integer(), server_default="8", nullable=False),
        sa.Column(
            "scheduled_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "handler_state",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_outbox_events")),
    )
    op.create_index(
        "outbox_events_aggregate_idx",
        "outbox_events",
        ["aggregate_id"],
        unique=False,
        postgresql_where=sa.text("aggregate_id IS NOT NULL"),
    )
    op.create_index(
        "outbox_events_correlation_idx",
        "outbox_events",
        ["correlation_id"],
        unique=False,
        postgresql_where=sa.text("correlation_id IS NOT NULL"),
    )
    op.create_index(
        "outbox_events_pending_idx",
        "outbox_events",
        ["scheduled_at"],
        unique=False,
        postgresql_where=sa.text("status = 'PENDING'"),
    )


def downgrade() -> None:
    op.drop_index(
        "outbox_events_pending_idx",
        table_name="outbox_events",
        postgresql_where=sa.text("status = 'PENDING'"),
    )
    op.drop_index(
        "outbox_events_correlation_idx",
        table_name="outbox_events",
        postgresql_where=sa.text("correlation_id IS NOT NULL"),
    )
    op.drop_index(
        "outbox_events_aggregate_idx",
        table_name="outbox_events",
        postgresql_where=sa.text("aggregate_id IS NOT NULL"),
    )
    op.drop_table("outbox_events")
    op.drop_index(
        "scheduled_jobs_pending_idx",
        table_name="scheduled_jobs",
        postgresql_where=sa.text("status = 'PENDING'"),
    )
    op.drop_table("scheduled_jobs")
