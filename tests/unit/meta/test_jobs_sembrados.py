"""Meta-test: registro de jobs y siembra en migraciones son biyectivos.

Un handler registrado sin fila sembrada NUNCA corre (el worker solo ejecuta
filas de scheduled_jobs); una fila sembrada sin handler envenena el worker con
errores en cada poll. Las dos mitades viven en ficheros distintos y este test
las mantiene sincronizadas.
"""

import re
from pathlib import Path

import app.core.jobs.handlers  # noqa: F401 - registra los handlers
from app.core.jobs.registry import job_registry

MIGRATIONS_DIR = Path(__file__).resolve().parents[3] / "migrations" / "versions"

# Aparece en los INSERT de siembra: VALUES ('nombre_del_job', ...)
_SEED_PATTERN = re.compile(r"INSERT INTO scheduled_jobs[^;]*?VALUES\s*\('([a-z_]+)'", re.DOTALL)


def _seeded_job_names() -> set[str]:
    names: set[str] = set()
    for migration in MIGRATIONS_DIR.glob("*.py"):
        names.update(_SEED_PATTERN.findall(migration.read_text(encoding="utf-8")))
    return names


def test_todo_job_registrado_esta_sembrado_y_viceversa() -> None:
    registered = set(job_registry._jobs)
    seeded = _seeded_job_names()

    sin_siembra = registered - seeded
    sin_handler = seeded - registered
    assert not sin_siembra, f"jobs registrados sin fila sembrada en migraciones: {sin_siembra}"
    assert not sin_handler, f"jobs sembrados sin handler registrado: {sin_handler}"
