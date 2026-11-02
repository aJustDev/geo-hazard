import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    SmallInteger,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, TimestampsMixin, UUIDPkMixin

CHANNELS = ("ntfy", "webhook")


class SubscriptionORM(UUIDPkMixin, TimestampsMixin, Base):
    """Suscripcion a un area vigilada por un canal (ADR-0021).

    `endpoint` es el servidor ntfy o la URL del webhook; `credential` el
    topic ntfy o la clave HMAC del webhook. Los genera la CLI y no se vuelven
    a mostrar. El estado de reintento vive aqui y no en cada entrega: un
    mensaje agrupa todas las pendientes de la suscripcion.
    """

    __tablename__ = "subscriptions"

    # RESTRICT: un area no desaparece debajo de una suscripcion viva.
    watch_area_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("watch_areas.id", ondelete="RESTRICT"), nullable=False
    )
    hazard_types: Mapped[list[str]] = mapped_column(ARRAY(String(30)), nullable=False)
    severity_min: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    channel: Mapped[str] = mapped_column(String(20), nullable=False)
    endpoint: Mapped[str] = mapped_column(String(2048), nullable=False)
    credential: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="active")
    paused_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    consecutive_failures: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    # Inicio de la racha de fallos en curso: tras 24 h seguidas se pausa.
    failing_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Proximo intento permitido: backoff tras un fallo y lease del reclamo.
    retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Sin URLs ni credenciales: clase de excepcion, esquema y host.
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "cardinality(hazard_types) > 0 AND hazard_types <@ "
            "ARRAY['wildfire', 'earthquake', 'weather_warning']::varchar[]",
            name="hazard_types_conocidos",
        ),
        CheckConstraint("severity_min BETWEEN 1 AND 4", name="severity_min_en_rango"),
        CheckConstraint("channel IN ('ntfy', 'webhook')", name="channel_conocido"),
        CheckConstraint("endpoint LIKE 'https://%'", name="endpoint_https"),
        CheckConstraint("status IN ('active', 'paused')", name="status_conocido"),
    )
