import uuid
from collections.abc import Collection
from datetime import UTC, datetime
from typing import Any

from geoalchemy2 import Geometry
from sqlalchemy import (
    Select,
    String,
    and_,
    func,
    literal,
    literal_column,
    or_,
    select,
    tuple_,
    type_coerce,
    update,
)
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.core.repo import BaseRepo
from app.hazards.models.hazard_event import HazardEventORM
from app.hazards.services.geometry import SRID_ETRS89_UTM30, SRID_WGS84

# Columnas que un upsert puede refrescar cuando el contenido cambia de verdad.
_UPDATABLE = ("hazard_type", "geom", "severity", "starts_at", "ends_at", "attrs", "content_hash")

# asyncpg limita cada sentencia a 32767 argumentos: un lote de EFFIS en
# temporada de incendios (~8k hotspots) lo revienta. El tamano de trozo se
# deriva del numero real de columnas del lote para que el limite siga siendo
# inalcanzable aunque el insert gane columnas.
_ASYNCPG_MAX_ARGS = 32767


def _apply_filters(
    stmt: Select[Any],
    *,
    hazard_types: list[str] | None = None,
    source: str | None = None,
    severity_min: int | None = None,
    starts_after: datetime | None = None,
    starts_before: datetime | None = None,
    active: bool | None = None,
) -> Select[Any]:
    """Filtros transversales compartidos por list/near/clusters."""
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
        # "Vigente ahora" (ADR-0016): ya empezo y sigue abierto (ends_at NULL
        # = la fuente aun lo sirve) o su ventana cubre este instante. Los
        # eventos puntuales (sismos, hotspots) tienen ends_at = starts_at,
        # asi que nunca cuentan como vigentes.
        now = datetime.now(UTC)
        stmt = stmt.where(
            and_(
                HazardEventORM.starts_at <= now,
                or_(HazardEventORM.ends_at.is_(None), HazardEventORM.ends_at >= now),
            )
        )
    return stmt


class HazardEventRepo(BaseRepo[HazardEventORM]):
    model = HazardEventORM

    async def upsert_batch(self, rows: list[dict[str, Any]]) -> tuple[int, int]:
        """Upsert idempotente por (source, external_id). Devuelve (insertados, actualizados).

        El WHERE sobre content_hash hace que un registro re-servido identico no
        toque disco, no dispare el trigger de updated_at y no cuente para el
        evento de lote (ADR-0008). El RETURNING usa el truco `xmax = 0`: en
        Postgres una fila recien insertada no tiene version previa (xmax 0),
        una actualizada si; las filas saltadas por el WHERE no se devuelven.

        El OR sobre ends_at es la contraparte de close_events (ADR-0010): si
        la fuente re-sirve abierto un evento que nosotros cerramos, la fuente
        manda y la fila se reabre aunque su contenido no haya cambiado.

        El lote se deduplica por (source, external_id) antes de ejecutar:
        dos filas con la misma clave en una sentencia rompen el ON CONFLICT
        DO UPDATE ("cannot affect row a second time"), y EFFIS puede
        re-servir un fire_id duplicado en la misma respuesta. Gana la ultima
        ocurrencia (la fuente manda). Despues se ejecuta en trozos acotados
        por el limite de argumentos de asyncpg; los trozos comparten
        transaccion, asi que el lote sigue siendo atomico para quien llama.
        """
        if not rows:
            return (0, 0)
        rows = list({(row["source"], row["external_id"]): row for row in rows}.values())
        chunk_rows = _ASYNCPG_MAX_ARGS // len(rows[0])

        inserted = 0
        updated = 0
        for start in range(0, len(rows), chunk_rows):
            chunk = rows[start : start + chunk_rows]
            stmt = pg_insert(HazardEventORM).values(chunk)
            upsert = stmt.on_conflict_do_update(  # type: ignore[var-annotated]
                index_elements=["source", "external_id"],
                set_={
                    **{col: getattr(stmt.excluded, col) for col in _UPDATABLE},
                    "updated_at": func.now(),
                },
                where=or_(
                    HazardEventORM.content_hash.is_distinct_from(stmt.excluded.content_hash),
                    HazardEventORM.ends_at.is_distinct_from(stmt.excluded.ends_at),
                ),
            ).returning(literal_column("(xmax = 0)").label("inserted"))

            result = await self.session.execute(upsert)
            flags = [row.inserted for row in result]
            inserted += sum(flags)
            updated += len(flags) - sum(flags)
        return (inserted, updated)

    async def close_events(
        self, *, source: str, external_ids: Collection[str], ended_at: datetime
    ) -> int:
        """Acota la ventana de vigencia: ends_at = ended_at para esos ids.

        Solo toca filas aun "abiertas" a esa hora (ends_at NULL o posterior):
        un aviso ya expirado conserva su expires original. Idempotente por
        construccion; devuelve cuantas filas cerro de verdad.
        """
        if not external_ids:
            return 0
        stmt = (
            update(HazardEventORM)
            .where(
                HazardEventORM.source == source,
                HazardEventORM.external_id.in_(external_ids),
                or_(HazardEventORM.ends_at.is_(None), HazardEventORM.ends_at > ended_at),
            )
            .values(ends_at=ended_at, updated_at=func.now())
            .returning(HazardEventORM.id)
        )
        result = await self.session.execute(stmt)
        return len(result.scalars().all())

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
        stmt = _apply_filters(
            stmt,
            hazard_types=hazard_types,
            source=source,
            severity_min=severity_min,
            starts_after=starts_after,
            starts_before=starts_before,
            active=active,
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

    def _near_stmt(
        self,
        *,
        latitude: float,
        longitude: float,
        radius_m: float,
        hazard_types: list[str] | None = None,
        source: str | None = None,
        severity_min: int | None = None,
        starts_after: datetime | None = None,
        starts_before: datetime | None = None,
        active: bool | None = None,
        limit: int = 100,
    ) -> Select[Any]:
        """Consulta de radio metrico en dos pasos (ADR-0011).

        El PARAMETRO se proyecta a 25830, nunca la columna (ADR-0005):
        1. Prefiltro barato: el circulo de radio_m se transforma de vuelta a
           4326 y su envelope se cruza con el GiST de geom.
        2. Refinado exacto: ST_DWithin en metros solo sobre los candidatos.

        El +1% del buffer del prefiltro absorbe que ST_Buffer aproxima el
        circulo con un poligono inscrito (sus cuerdas quedan por dentro);
        quien decide la pertenencia real es siempre el ST_DWithin.
        """
        center = func.ST_Transform(
            func.ST_SetSRID(func.ST_MakePoint(longitude, latitude), SRID_WGS84),
            SRID_ETRS89_UTM30,
        )
        geom_metric = func.ST_Transform(HazardEventORM.geom, SRID_ETRS89_UTM30)
        distance = func.ST_Distance(geom_metric, center).label("distance_m")
        prefilter = func.ST_Envelope(
            func.ST_Transform(func.ST_Buffer(center, radius_m * 1.01), SRID_WGS84)
        )

        stmt = select(HazardEventORM, distance).where(
            HazardEventORM.geom.ST_Intersects(prefilter),
            func.ST_DWithin(geom_metric, center, radius_m),
        )
        stmt = _apply_filters(
            stmt,
            hazard_types=hazard_types,
            source=source,
            severity_min=severity_min,
            starts_after=starts_after,
            starts_before=starts_before,
            active=active,
        )
        return stmt.order_by(distance.asc(), HazardEventORM.id).limit(limit)

    async def near_page(
        self,
        *,
        latitude: float,
        longitude: float,
        radius_m: float,
        hazard_types: list[str] | None = None,
        source: str | None = None,
        severity_min: int | None = None,
        starts_after: datetime | None = None,
        starts_before: datetime | None = None,
        active: bool | None = None,
        limit: int = 100,
    ) -> list[tuple[HazardEventORM, float]]:
        """Eventos a menos de radius_m del punto, ordenados por distancia.

        Para poligonos la distancia es al borde: 0 si el punto cae dentro.
        Sin cursor: una consulta de radio devuelve "los N mas cercanos".
        """
        stmt = self._near_stmt(
            latitude=latitude,
            longitude=longitude,
            radius_m=radius_m,
            hazard_types=hazard_types,
            source=source,
            severity_min=severity_min,
            starts_after=starts_after,
            starts_before=starts_before,
            active=active,
            limit=limit,
        )
        result = await self.session.execute(stmt)
        return [(row[0], float(row[1])) for row in result.all()]

    async def cluster_rows(
        self,
        *,
        eps_m: float,
        min_points: int,
        hazard_types: list[str] | None = None,
        source: str | None = None,
        severity_min: int | None = None,
        starts_after: datetime | None = None,
        starts_before: datetime | None = None,
        active: bool | None = None,
    ) -> list[dict[str, Any]]:
        """Agregados por cluster DBSCAN sobre la proyeccion metrica (ADR-0011).

        ST_ClusterDBSCAN es funcion ventana: cada fila conserva su cluster_id
        y el GROUP BY exterior agrega centroide/recuento/severidad/rango
        temporal. El ruido (cluster_id NULL: puntos sin min_points vecinos a
        eps_m) se excluye: no es un cluster. El centroide se calcula en 25830
        (centroide metrico) y se devuelve en 4326.
        """
        geom_metric = func.ST_Transform(HazardEventORM.geom, SRID_ETRS89_UTM30)
        base = select(
            HazardEventORM.severity,
            HazardEventORM.starts_at,
            geom_metric.label("geom_metric"),
            func.ST_ClusterDBSCAN(geom_metric, eps_m, min_points).over().label("cluster_id"),
        )
        base = _apply_filters(
            base,
            hazard_types=hazard_types,
            source=source,
            severity_min=severity_min,
            starts_after=starts_after,
            starts_before=starts_before,
            active=active,
        )
        clustered = base.subquery("clustered")

        centroid = type_coerce(
            func.ST_Transform(
                func.ST_Centroid(func.ST_Collect(clustered.c.geom_metric)), SRID_WGS84
            ),
            Geometry(geometry_type="POINT", srid=SRID_WGS84),
        ).label("centroid")
        stmt = (
            select(
                clustered.c.cluster_id,
                func.count().label("count"),
                func.max(clustered.c.severity).label("max_severity"),
                func.min(clustered.c.starts_at).label("first_starts_at"),
                func.max(clustered.c.starts_at).label("last_starts_at"),
                centroid,
            )
            .where(clustered.c.cluster_id.is_not(None))
            .group_by(clustered.c.cluster_id)
            .order_by(func.count().desc(), clustered.c.cluster_id)
        )
        result = await self.session.execute(stmt)
        return [dict(row) for row in result.mappings()]

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
