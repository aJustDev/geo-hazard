from datetime import datetime
from typing import Any

from geoalchemy2 import Geometry
from geoalchemy2.elements import WKBElement
from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Index,
    SmallInteger,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, TimestampsMixin, UUIDPkMixin

# CHECK en vez de ENUM nativo: anadir un valor es DROP/ADD CONSTRAINT sin lock
# largo; un ENUM complica las migraciones sin aportar nada aqui (ADR-0004).
SOURCES = ("effis", "ign", "aemet")
HAZARD_TYPES = ("wildfire", "earthquake", "weather_warning")


class HazardEventORM(UUIDPkMixin, TimestampsMixin, Base):
    """Evento de peligro unificado de cualquier fuente (ADR-0004).

    La heterogeneidad de las fuentes vive en `attrs` (crudos por fuente,
    validados por schema en la frontera del driver); las columnas comunes
    permiten que bbox/radio/clustering sean UNA query sobre UN GiST.
    """

    __tablename__ = "hazard_events"

    source: Mapped[str] = mapped_column(String(20), nullable=False)
    hazard_type: Mapped[str] = mapped_column(String(30), nullable=False)
    # Identificador nativo de la fuente: la clave de idempotencia del upsert.
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    # GEOMETRY generico: EFFIS mezcla puntos (hotspots) y poligonos (areas
    # quemadas) dentro de la misma fuente; el GiST indexa igual (ADR-0005).
    geom: Mapped[WKBElement] = mapped_column(
        Geometry(geometry_type="GEOMETRY", srid=4326, spatial_index=True),
        nullable=False,
    )
    # Escala ordinal comun 1-4 (ADR-0009); el valor crudo queda en attrs.
    severity: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # Solo eventos con ventana (avisos); NULL = instantaneo.
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attrs: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb"), nullable=False
    )
    # sha256 del payload canonico: un re-servido identico no toca disco ni
    # emite eventos (ADR-0008).
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    __table_args__ = (
        UniqueConstraint("source", "external_id", name="uq_hazard_events_source_external_id"),
        CheckConstraint("source IN ('effis', 'ign', 'aemet')", name="source_conocida"),
        CheckConstraint(
            "hazard_type IN ('wildfire', 'earthquake', 'weather_warning')",
            name="hazard_type_conocido",
        ),
        CheckConstraint("severity BETWEEN 1 AND 4", name="severity_en_rango"),
        # Filtros temporales por tipo (la ordenacion keyset tambien lo usa).
        Index("ix_hazard_events_hazard_type_starts_at", "hazard_type", text("starts_at DESC")),
        # Parcial: solo los eventos con ventana participan en `active=true`.
        Index(
            "ix_hazard_events_ends_at_activos",
            "ends_at",
            postgresql_where=text("ends_at IS NOT NULL"),
        ),
    )
