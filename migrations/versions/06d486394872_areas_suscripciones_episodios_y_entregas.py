"""areas, suscripciones, episodios y entregas

Esquema de los avisos por area vigilada (ADR-0021). Tablas nuevas y vacias:
no aplican las reglas DDL sin-downtime.

Quita provinces.inner_geom (la provincia encogida 1 km de a85d87823c53):
contra los avisos reales de prod dejaba pasar zonas AEMET vecinas
(Almanzora en Murcia) y perdia zonas costeras. Un poligono pertenece ahora a
la provincia con la que mas solapa, lo que no necesita geometria propia.

Revision ID: 06d486394872
Revises: a85d87823c53
Create Date: 2026-11-02 20:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from geoalchemy2 import Geometry
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "06d486394872"
down_revision: str | None = "a85d87823c53"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _multipolygon(name: str) -> sa.Column:
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


def _id() -> sa.Column:
    return sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False)


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    ]


def upgrade() -> None:
    op.drop_geospatial_index(
        "idx_provinces_inner_geom", table_name="provinces", column_name="inner_geom"
    )
    op.drop_geospatial_column("provinces", "inner_geom")

    op.create_geospatial_table(
        "watch_areas",
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("params", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("label", sa.String(length=200), nullable=False),
        _multipolygon("geom"),
        _id(),
        *_timestamps(),
        sa.CheckConstraint(
            "kind IN ('province', 'bbox', 'circle')", name=op.f("ck_watch_areas_kind_conocido")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_watch_areas")),
    )
    op.create_geospatial_index(
        "idx_watch_areas_geom",
        "watch_areas",
        ["geom"],
        unique=False,
        postgresql_using="gist",
        postgresql_ops={},
    )

    op.create_table(
        "subscriptions",
        sa.Column("watch_area_id", sa.UUID(), nullable=False),
        sa.Column("hazard_types", postgresql.ARRAY(sa.String(length=30)), nullable=False),
        sa.Column("severity_min", sa.SmallInteger(), nullable=False),
        sa.Column("channel", sa.String(length=20), nullable=False),
        sa.Column("endpoint", sa.String(length=2048), nullable=False),
        sa.Column("credential", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="active", nullable=False),
        sa.Column("paused_reason", sa.Text(), nullable=True),
        sa.Column("consecutive_failures", sa.Integer(), server_default="0", nullable=False),
        sa.Column("failing_since", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        _id(),
        *_timestamps(),
        sa.CheckConstraint(
            "cardinality(hazard_types) > 0 AND hazard_types <@ "
            "ARRAY['wildfire', 'earthquake', 'weather_warning']::varchar[]",
            name=op.f("ck_subscriptions_hazard_types_conocidos"),
        ),
        sa.CheckConstraint(
            "severity_min BETWEEN 1 AND 4", name=op.f("ck_subscriptions_severity_min_en_rango")
        ),
        sa.CheckConstraint(
            "channel IN ('ntfy', 'webhook')", name=op.f("ck_subscriptions_channel_conocido")
        ),
        sa.CheckConstraint(
            "endpoint LIKE 'https://%'", name=op.f("ck_subscriptions_endpoint_https")
        ),
        sa.CheckConstraint(
            "status IN ('active', 'paused')", name=op.f("ck_subscriptions_status_conocido")
        ),
        sa.ForeignKeyConstraint(
            ["watch_area_id"],
            ["watch_areas.id"],
            name=op.f("fk_subscriptions_watch_area_id_watch_areas"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_subscriptions")),
    )

    op.create_table(
        "notification_episodes",
        sa.Column("subscription_id", sa.UUID(), nullable=False),
        sa.Column("key", sa.String(length=300), nullable=False),
        sa.Column("notified_severity", sa.SmallInteger(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_matched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        _id(),
        sa.ForeignKeyConstraint(
            ["subscription_id"],
            ["subscriptions.id"],
            name=op.f("fk_notification_episodes_subscription_id_subscriptions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_notification_episodes")),
    )
    op.create_index(
        "uq_notification_episodes_abierto",
        "notification_episodes",
        ["subscription_id", "key"],
        unique=True,
        postgresql_where=sa.text("closed_at IS NULL"),
    )
    op.create_index(
        "ix_notification_episodes_last_matched_at", "notification_episodes", ["last_matched_at"]
    )

    op.create_table(
        "notification_deliveries",
        sa.Column("subscription_id", sa.UUID(), nullable=False),
        sa.Column("episode_id", sa.UUID(), nullable=False),
        sa.Column("severity", sa.SmallInteger(), nullable=False),
        sa.Column("reason", sa.String(length=20), nullable=False),
        sa.Column("items", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("item_count", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="pending", nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("message_id", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        _id(),
        sa.CheckConstraint(
            "reason IN ('opened', 'escalated')",
            name=op.f("ck_notification_deliveries_reason_conocido"),
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'sent', 'failed')",
            name=op.f("ck_notification_deliveries_status_conocido"),
        ),
        sa.CheckConstraint(
            "severity BETWEEN 1 AND 4", name=op.f("ck_notification_deliveries_severity_en_rango")
        ),
        sa.ForeignKeyConstraint(
            ["subscription_id"],
            ["subscriptions.id"],
            name=op.f("fk_notification_deliveries_subscription_id_subscriptions"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["episode_id"],
            ["notification_episodes.id"],
            name=op.f("fk_notification_deliveries_episode_id_notification_episodes"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_notification_deliveries")),
        sa.UniqueConstraint(
            "episode_id", "severity", name="uq_notification_deliveries_episode_id_severity"
        ),
    )
    op.create_index(
        "ix_notification_deliveries_pendientes",
        "notification_deliveries",
        ["subscription_id", "created_at"],
        postgresql_where=sa.text("status = 'pending'"),
    )


def downgrade() -> None:
    op.drop_table("notification_deliveries")
    op.drop_table("notification_episodes")
    op.drop_table("subscriptions")
    op.drop_geospatial_index("idx_watch_areas_geom", table_name="watch_areas", column_name="geom")
    op.drop_geospatial_table("watch_areas")

    # Restaura inner_geom con la misma expresion que a85d87823c53.
    op.add_geospatial_column(
        "provinces",
        sa.Column(
            "inner_geom",
            Geometry(geometry_type="MULTIPOLYGON", srid=4326, spatial_index=False),
            nullable=True,
        ),
    )
    op.execute(
        """
        UPDATE provinces SET inner_geom = CASE WHEN ST_IsEmpty(i) THEN geom ELSE i END
        FROM (SELECT code AS c, ST_Multi(ST_CollectionExtract(ST_MakeValid(
                  ST_Buffer(geom::geography, -1000)::geometry), 3)) AS i
              FROM provinces) AS buffered
        WHERE code = buffered.c
        """
    )
    op.alter_column("provinces", "inner_geom", nullable=False)
    op.create_geospatial_index(
        "idx_provinces_inner_geom",
        "provinces",
        ["inner_geom"],
        unique=False,
        postgresql_using="gist",
        postgresql_ops={},
    )
