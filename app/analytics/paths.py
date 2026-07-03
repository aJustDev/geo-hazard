"""Rutas de los ficheros que lee el plano analitico.

El layout de los GeoParquet ES el contrato entre planos (ADR-0012): hazards
los escribe bajo {DATA_DIR}/exports y analytics los lee de alli; no
comparten nada mas. La referencia de provincias es distinta: viaja
commiteada en el repo (ADR-0013), no en el volumen de datos.
"""

from pathlib import Path

from app.core.config import settings

_REPO_ROOT = Path(__file__).resolve().parents[2]

PROVINCES_PARQUET = _REPO_ROOT / "data" / "reference" / "provinces_es.parquet"


def source_snapshot(source: str) -> Path:
    return Path(settings.DATA_DIR) / "exports" / f"hazard_events_{source}.parquet"


__all__ = ["PROVINCES_PARQUET", "source_snapshot"]
