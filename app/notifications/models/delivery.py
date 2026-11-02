import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, UUIDPkMixin


class NotificationDeliveryORM(UUIDPkMixin, Base):
    """Un aviso pendiente o enviado: un episodio que abre o escala (ADR-0021).

    `items` es una foto de los eventos casados como GeoJSON Features, asi la
    entrega nunca lee hazard_events. Unica por (episodio, severidad): un
    handler reintentado no la duplica.
    """

    __tablename__ = "notification_deliveries"

    subscription_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("subscriptions.id", ondelete="CASCADE"), nullable=False
    )
    episode_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("notification_episodes.id", ondelete="CASCADE"),
        nullable=False,
    )
    severity: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    reason: Mapped[str] = mapped_column(String(20), nullable=False)
    items: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    # Cuantos eventos casaron; items guarda como mucho unos pocos.
    item_count: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="pending")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    # Mensaje en el que salio: varias entregas comparten uno.
    message_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint(
            "episode_id", "severity", name="uq_notification_deliveries_episode_id_severity"
        ),
        CheckConstraint("reason IN ('opened', 'escalated')", name="reason_conocido"),
        CheckConstraint("status IN ('pending', 'sent', 'failed')", name="status_conocido"),
        CheckConstraint("severity BETWEEN 1 AND 4", name="severity_en_rango"),
        Index(
            "ix_notification_deliveries_pendientes",
            "subscription_id",
            "created_at",
            postgresql_where=text("status = 'pending'"),
        ),
    )
