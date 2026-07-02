import uuid
from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class ScheduledJobORM(Base):
    """Job recurrente Postgres-nativo. Una fila por job_name (sembrada por
    migracion); el JobWorker la claima con lease y la reprograma cada
    interval_seconds. status solo toma 'PENDING'/'RUNNING'.
    """

    __tablename__ = "scheduled_jobs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    job_name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, default=None)
    interval_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="PENDING")
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    next_run_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    last_error: Mapped[str | None] = mapped_column(Text, default=None)
    run_count: Mapped[int] = mapped_column(default=0, server_default="0")
    claimed_by: Mapped[str | None] = mapped_column(String(255), default=None)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    __table_args__ = (
        Index(
            "scheduled_jobs_pending_idx",
            "next_run_at",
            postgresql_where=(status == "PENDING"),
        ),
    )
