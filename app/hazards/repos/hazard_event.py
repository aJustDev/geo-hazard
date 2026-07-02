import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import String, and_, func, literal, literal_column, select, tuple_
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.core.repo import BaseRepo
from app.hazards.models.hazard_event import HazardEventORM
from app.hazards.services.geometry import SRID_WGS84

# Columnas que un upsert puede refrescar cuando el contenido cambia de verdad.
_UPDATABLE = ("hazard_type", "geom", "severity", "starts_at", "ends_at", "attrs", "content_hash")


class HazardEventRepo(BaseRepo[HazardEventORM]):
    model = HazardEventORM

    async def upsert_batch(self, rows: list[dict[str, Any]]) -> tuple[int, int]:
        """Upsert idempotente por (source, external_id). Devuelve (insertados, actualizados).

        El WHERE sobre content_hash hace que un registro re-servido identico no
        toque disco, no dispare el trigger de updated_at y no cuente para el
        evento de lote (ADR-0008). El RETURNING usa el truco `xmax = 0`: en
        Postgres una fila recien insertada no tiene version previa (xmax 0),
        una actualizada si; las filas saltadas por el WHERE no se devuelven.
        """
        if not rows:
            return (0, 0)

        stmt = pg_insert(HazardEventORM).values(rows)
        upsert = stmt.on_conflict_do_update(  # type: ignore[var-annotated]
            index_elements=["source", "external_id"],
            set_={
                **{col: getattr(stmt.excluded, col) for col in _UPDATABLE},
                "updated_at": func.now(),
            },
            where=HazardEventORM.content_hash.is_distinct_from(stmt.excluded.content_hash),
        ).returning(literal_column("(xmax = 0)").label("inserted"))

        result = await self.session.execute(upsert)
        flags = [row.inserted for row in result]
        inserted = sum(flags)
        return (inserted, len(flags) - inserted)

    async def list_page(
        self,
        *,
        bbox: tuple[float, float, float, float] | None = None,
        hazard_types: list[str] | None = None,
        source: str | None = None,
        severity_min: int | None = None,
        starts_after: datetime | None = None,
        starts_before: datetime | None = None,
        active: bool | None = None,
        limit: int = 100,
        cursor: tuple[datetime, uuid.UUID] | None = None,
    ) -> tuple[list[HazardEventORM], tuple[datetime, uuid.UUID] | None]:
        """Pagina keyset ordenada por (starts_at DESC, id DESC).

        Devuelve (items, clave_de_la_siguiente_pagina). Se pide limit+1 para
        saber si hay mas paginas sin un COUNT aparte.
        """
        stmt = select(HazardEventORM)

        if bbox is not None:
            envelope = func.ST_MakeEnvelope(*bbox, SRID_WGS84)
            stmt = stmt.where(HazardEventORM.geom.ST_Intersects(envelope))
        if hazard_types:
            stmt = stmt.where(HazardEventORM.hazard_type.in_(hazard_types))
        if source is not None:
            stmt = stmt.where(HazardEventORM.source == source)
        if severity_min is not None:
            stmt = stmt.where(HazardEventORM.severity >= severity_min)
        if starts_after is not None:
            stmt = stmt.where(HazardEventORM.starts_at >= starts_after)
        if starts_before is not None:
            stmt = stmt.where(HazardEventORM.starts_at <= starts_before)
        if active:
            # "Vigente ahora": solo tiene sentido para eventos con ventana.
            now = datetime.now(UTC)
            stmt = stmt.where(
                and_(
                    HazardEventORM.ends_at.is_not(None),
                    HazardEventORM.starts_at <= now,
                    HazardEventORM.ends_at >= now,
                )
            )
        if cursor is not None:
            stmt = stmt.where(
                tuple_(HazardEventORM.starts_at, HazardEventORM.id)
                < tuple_(literal(cursor[0]), literal(cursor[1]))
            )

        stmt = stmt.order_by(HazardEventORM.starts_at.desc(), HazardEventORM.id.desc()).limit(
            limit + 1
        )
        rows = list((await self.session.execute(stmt)).scalars().all())

        if len(rows) <= limit:
            return (rows, None)
        page = rows[:limit]
        last = page[-1]
        return (page, (last.starts_at, last.id))

    async def fetch_export_rows(self, source: str) -> list[dict[str, Any]]:
        """Filas planas para el snapshot GeoParquet: geometria como WKB binario.

        attrs viaja como texto JSON para que el esquema Parquet sea estable
        entre lotes (un struct inferido cambiaria con cada clave nueva).
        """
        stmt = (
            select(
                HazardEventORM.id.cast(String).label("id"),
                HazardEventORM.source,
                HazardEventORM.hazard_type,
                HazardEventORM.external_id,
                HazardEventORM.severity,
                HazardEventORM.starts_at,
                HazardEventORM.ends_at,
                func.ST_AsBinary(HazardEventORM.geom).label("wkb"),
                HazardEventORM.attrs.cast(String).label("attrs"),
            )
            .where(HazardEventORM.source == source)
            .order_by(HazardEventORM.starts_at)
        )
        result = await self.session.execute(stmt)
        return [dict(row) for row in result.mappings()]
