from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class SourceSyncStateORM(Base):
    """Estado de sincronizacion por fuente (ADR-0008).

    Separado de scheduled_jobs a proposito: el cursor es conocimiento del
    dominio de ingesta; scheduled_jobs es infraestructura generica de
    scheduling y no debe saber que existe EFFIS.
    """

    __tablename__ = "source_sync_state"

    source: Mapped[str] = mapped_column(String(20), primary_key=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Semantica por fuente: IGN {"last_event_at"}, EFFIS {"etag"}, AEMET {}.
    cursor: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb"), nullable=False
    )
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    consecutive_failures: Mapped[int] = mapped_column(Integer, server_default="0", nullable=False)
