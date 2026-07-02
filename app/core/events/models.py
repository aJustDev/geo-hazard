import uuid
from datetime import datetime

from sqlalchemy import DateTime, Index, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.config import settings
from app.core.db import Base


class OutboxEventORM(Base):
    """Evento de outbox transaccional. Se inserta en la misma transaccion que
    la escritura de dominio (EventBus.publish) y lo consume el OutboxWorker
    con FOR UPDATE SKIP LOCKED, un evento por transaccion.
    """

    __tablename__ = "outbox_events"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    aggregate_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), default=None)
    correlation_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), default=None)
    event_type: Mapped[str] = mapped_column(String(255), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="PENDING")
    retry_count: Mapped[int] = mapped_column(default=0, server_default="0")
    max_retries: Mapped[int] = mapped_column(
        default=settings.OUTBOX_MAX_RETRIES,
        server_default=str(settings.OUTBOX_MAX_RETRIES),
    )
    scheduled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    last_error: Mapped[str | None] = mapped_column(Text, default=None)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    handler_state: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")

    __table_args__ = (
        Index(
            "outbox_events_pending_idx",
            "scheduled_at",
            postgresql_where=(status == "PENDING"),
        ),
        Index(
            "outbox_events_aggregate_idx",
            "aggregate_id",
            postgresql_where=(aggregate_id.isnot(None)),
        ),
        Index(
            "outbox_events_correlation_idx",
            "correlation_id",
            postgresql_where=(correlation_id.isnot(None)),
        ),
    )
