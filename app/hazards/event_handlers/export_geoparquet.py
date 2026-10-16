"""Consumidor de hazards.batch_ingested: snapshot GeoParquet por fuente.

Este es el nacimiento del plano analitico (ADR-0007): EFFIS y AEMET son
ventanas rodantes, asi que cada lote con cambios reescribe el snapshot
completo de su fuente. La escritura es atomica (temporal unico + os.replace) e
idempotente: reintentar el evento produce el mismo resultado.
"""

import logging
import os
from pathlib import Path
from typing import Any
from uuid import uuid4

import duckdb
import pyarrow as pa

from app.core.concurrency import run_blocking
from app.core.config import settings
from app.core.db import async_session_factory
from app.core.events.dispatcher import dispatcher
from app.hazards.repos.hazard_event import HazardEventRepo

logger = logging.getLogger(__name__)

_SCHEMA = pa.schema(
    [
        ("id", pa.string()),
        ("source", pa.string()),
        ("hazard_type", pa.string()),
        ("external_id", pa.string()),
        ("severity", pa.int16()),
        ("starts_at", pa.timestamp("us", tz="UTC")),
        ("ends_at", pa.timestamp("us", tz="UTC")),
        ("wkb", pa.binary()),
        ("attrs", pa.string()),
    ]
)


@dispatcher.register("hazards.batch_ingested")
async def export_geoparquet(payload: dict[str, Any]) -> None:
    source = payload["source"]
    async with async_session_factory() as session:
        rows = await HazardEventRepo(session).fetch_export_rows(source)

    path = Path(settings.DATA_DIR) / "exports" / f"hazard_events_{source}.parquet"
    # DuckDB es sincrono: fuera del event loop siempre (mismo patron que el
    # computo pesado en apsis).
    await run_blocking(_write_snapshot, rows, path)
    logger.info("geoparquet snapshot written: %s (%d rows)", path, len(rows))


def _write_snapshot(rows: list[dict[str, Any]], path: Path) -> None:
    # Esquema explicito: la inferencia de tipos cambiaria el esquema del
    # parquet entre lotes (p.ej. ends_at todo NULL) y romperia a los lectores.
    table = pa.Table.from_pylist(rows, schema=_SCHEMA)

    # Temporal unico por escritura: el handler corre en un hilo que wait_for no
    # puede cancelar, asi que tras un timeout el reintento puede solaparse con
    # la escritura anterior de la misma fuente.
    tmp = path.with_name(f"{path.name}.{uuid4().hex}.tmp")
    con = duckdb.connect()
    try:
        con.execute("INSTALL spatial; LOAD spatial")
        con.register("snapshot", table)
        # ST_GeomFromWKB via DuckDB spatial escribe metadatos GeoParquet
        # correctos; el resto de columnas pasan tal cual.
        con.execute(
            "COPY (SELECT * EXCLUDE (wkb), ST_GeomFromWKB(wkb) AS geom FROM snapshot "
            "ORDER BY starts_at) TO ? (FORMAT PARQUET)",
            [str(tmp)],
        )
        os.replace(tmp, path)
    finally:
        con.close()
        tmp.unlink(missing_ok=True)


__all__ = ["export_geoparquet"]
