"""Escritura del snapshot GeoParquet (contrato entre planos, ADR-0012).

El handler corre en un hilo bajo wait_for: si excede el timeout, la corutina
se cancela pero el hilo sigue escribiendo, y el reintento (o una segunda
replica) escribe el mismo snapshot a la vez. Ninguna escritura concurrente
puede dejar un parquet corrupto ni temporales huerfanos.
"""

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

import duckdb
import pytest
import shapely

from app.hazards.event_handlers.export_geoparquet import _write_snapshot


def _rows(n: int) -> list[dict]:
    return [
        {
            "id": f"ev-{i}",
            "source": "effis",
            "hazard_type": "wildfire",
            "external_id": f"ev-{i}",
            "severity": 2,
            "starts_at": datetime(2026, 7, 1, tzinfo=UTC),
            "ends_at": None,
            "wkb": shapely.to_wkb(shapely.Point(-5.0 + i * 0.001, 39.0)),
            "attrs": json.dumps({}),
        }
        for i in range(n)
    ]


def test_escrituras_concurrentes_dejan_un_snapshot_valido(tmp_path: Path) -> None:
    path = tmp_path / "hazard_events_effis.parquet"
    sizes = [50, 60, 70, 80, 90, 100, 110, 120]

    with ThreadPoolExecutor(max_workers=len(sizes)) as pool:
        futures = [pool.submit(_write_snapshot, _rows(n), path) for n in sizes]
        for f in futures:
            f.result()  # ninguna escritura debe fallar

    count = duckdb.execute("SELECT count(*) FROM read_parquet(?)", [str(path)]).fetchone()
    assert count is not None
    assert count[0] in sizes
    assert list(tmp_path.glob("*.tmp")) == []


def test_escritura_fallida_no_deja_temporal(tmp_path: Path) -> None:
    path = tmp_path / "hazard_events_effis.parquet"
    rows = _rows(1)
    rows[0]["wkb"] = b"esto no es wkb"

    with pytest.raises(duckdb.Error):
        _write_snapshot(rows, path)

    assert not path.exists()
    assert list(tmp_path.iterdir()) == []
