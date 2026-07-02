"""hazard events y estado de sincronizacion

Dominio de la fase EFFIS: la tabla unificada hazard_events (ADR-0004, con
GiST sobre geom y CHECKs en vez de ENUMs), source_sync_state (cursor por
fuente, ADR-0008) y la siembra del job effis_sync cada 4h. Tablas nuevas y
vacias: no aplican las reglas DDL sin-downtime (CONCURRENTLY/NOT VALID), que
son para tablas ya en produccion.

Revision ID: 4a7755cba66d
Revises: 649b55b28ba3
Create Date: 2026-07-02 22:36:10.674539

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from geoalchemy2 import Geometry
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "4a7755cba66d"
down_revision: str | None = "649b55b28ba3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_geospatial_table(
        "hazard_events",
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("hazard_type", sa.String(length=30), nullable=False),
        sa.Column("external_id", sa.String(length=255), nullable=False),
        sa.Column(
            "geom",
            Geometry(
                geometry_type="GEOMETRY",
                srid=4326,
                dimension=2,
                spatial_index=False,
                from_text="ST_GeomFromEWKT",
                name="geometry",
                nullable=False,
            ),
            nullable=False,
        ),
        sa.Column("severity", sa.SmallInteger(), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "attrs",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "source IN ('effis', 'ign', 'aemet')", name=op.f("ck_hazard_events_source_conocida")
        ),
        sa.CheckConstraint(
            "hazard_type IN ('wildfire', 'earthquake', 'weather_warning')",
            name=op.f("ck_hazard_events_hazard_type_conocido"),
        ),
        sa.CheckConstraint(
            "severity BETWEEN 1 AND 4", name=op.f("ck_hazard_events_severity_en_rango")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_hazard_events")),
        sa.UniqueConstraint("source", "external_id", name="uq_hazard_events_source_external_id"),
    )
    op.create_geospatial_index(
        "idx_hazard_events_geom",
        "hazard_events",
        ["geom"],
        unique=False,
        postgresql_using="gist",
        postgresql_ops={},
    )
    op.create_index(
        "ix_hazard_events_hazard_type_starts_at",
        "hazard_events",
        ["hazard_type", sa.literal_column("starts_at DESC")],
        unique=False,
    )
    op.create_index(
        "ix_hazard_events_ends_at_activos",
        "hazard_events",
        ["ends_at"],
        unique=False,
        postgresql_where=sa.text("ends_at IS NOT NULL"),
    )

    op.create_table(
        "source_sync_state",
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "cursor",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("consecutive_failures", sa.Integer(), server_default="0", nullable=False),
        sa.PrimaryKeyConstraint("source", name=op.f("pk_source_sync_state")),
    )

    # Siembra el job de sincronizacion EFFIS (4h: la fuente publica ~6
    # actualizaciones diarias; pollear mas solo re-sirve contenido identico).
    op.execute(
        "INSERT INTO scheduled_jobs (job_name, description, interval_seconds, next_run_at, status) "
        "VALUES ('effis_sync', 'Sincroniza incendios EFFIS (hotspots + areas quemadas) y "
        "publica hazards.batch_ingested.', 14400, now(), 'PENDING') "
        "ON CONFLICT (job_name) DO NOTHING"
    )


def downgrade() -> None:
    op.execute("DELETE FROM scheduled_jobs WHERE job_name = 'effis_sync'")
    op.drop_table("source_sync_state")
    op.drop_index(
        "ix_hazard_events_ends_at_activos",
        table_name="hazard_events",
        postgresql_where=sa.text("ends_at IS NOT NULL"),
    )
    op.drop_index("ix_hazard_events_hazard_type_starts_at", table_name="hazard_events")
    op.drop_geospatial_index(
        "idx_hazard_events_geom",
        table_name="hazard_events",
        postgresql_using="gist",
        column_name="geom",
    )
    op.drop_geospatial_table("hazard_events")
