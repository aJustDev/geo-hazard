import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, SmallInteger, String, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, UUIDPkMixin


class NotificationEpisodeORM(UUIDPkMixin, Base):
    """Episodio de una suscripcion: lo que agrupa los avisos de un mismo
    fenomeno, sismo o incendio para no repetirlos (ADR-0021).

    `key` es `aemet:<fenomeno>` o `<source>:<external_id>`. `expires_at` solo
    en AEMET (max ends_at ingerido); NULL = vigente siempre (IGN, EFFIS).
    """

    __tablename__ = "notification_episodes"

    subscription_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("subscriptions.id", ondelete="CASCADE"), nullable=False
    )
    key: Mapped[str] = mapped_column(String(300), nullable=False)
    notified_severity: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_matched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        # Un unico episodio abierto por suscripcion y clave.
        Index(
            "uq_notification_episodes_abierto",
            "subscription_id",
            "key",
            unique=True,
            postgresql_where=text("closed_at IS NULL"),
        ),
        # Purga por retencion.
        Index("ix_notification_episodes_last_matched_at", "last_matched_at"),
    )
