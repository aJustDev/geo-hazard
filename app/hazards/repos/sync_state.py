from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.hazards.models.sync_state import SourceSyncStateORM


class SourceSyncStateRepo:
    """Estado de sincronizacion por fuente. No hereda BaseRepo: la PK es el
    nombre de la fuente, no un uuid, y su API son dos transiciones (exito /
    fallo), no CRUD.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def record_success(self, source: str, *, cursor: dict[str, Any] | None = None) -> None:
        now = datetime.now(UTC)
        values: dict[str, Any] = {
            "source": source,
            "last_run_at": now,
            "last_success_at": now,
            "last_error": None,
            "consecutive_failures": 0,
        }
        if cursor is not None:
            values["cursor"] = cursor
        stmt = pg_insert(SourceSyncStateORM).values(values)
        stmt = stmt.on_conflict_do_update(
            index_elements=["source"],
            set_={k: getattr(stmt.excluded, k) for k in values if k != "source"},
        )
        await self.session.execute(stmt)

    async def record_failure(self, source: str, error: str) -> None:
        # El traceback completo va al log; aqui solo el resumen operativo.
        values: dict[str, Any] = {
            "source": source,
            "last_run_at": datetime.now(UTC),
            "last_error": error[:500],
            "consecutive_failures": 1,
        }
        stmt = pg_insert(SourceSyncStateORM).values(values)
        stmt = stmt.on_conflict_do_update(
            index_elements=["source"],
            set_={
                "last_run_at": stmt.excluded.last_run_at,
                "last_error": stmt.excluded.last_error,
                "consecutive_failures": SourceSyncStateORM.consecutive_failures + 1,
            },
        )
        await self.session.execute(stmt)

    async def get(self, source: str) -> SourceSyncStateORM | None:
        return await self.session.get(SourceSyncStateORM, source)

    async def list_all(self) -> list[SourceSyncStateORM]:
        result = await self.session.execute(
            select(SourceSyncStateORM).order_by(SourceSyncStateORM.source)
        )
        return list(result.scalars().all())
