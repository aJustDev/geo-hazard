# Comandos habituales de desarrollo; `just` sin argumentos los lista.
# Requiere uv y Docker. La config local sale de .env.local (copia de .env.example).

default:
    @just --list

# Instala dependencias (runtime + dev) desde el lock
sync:
    uv sync

# Levanta la BD de desarrollo (PostGIS en 127.0.0.1:5433)
db:
    docker compose -f compose.dev.yml up -d --wait

# Aplica las migraciones a la BD de desarrollo
migrate:
    uv run alembic upgrade head

# API en local con recarga y logs JSON (http://127.0.0.1:8000/docs). Acepta argumentos de uvicorn, p.ej. --port 8010
run *args:
    uv run uvicorn app.main:app --reload --log-config log_config.json {{ args }}

# Tests unitarios: sin red ni Docker. Acepta argumentos de pytest
test *args:
    uv run pytest {{ args }}

# Suite completa como en CI: unit + integracion (testcontainers) + gates de cobertura
test-all:
    uv run pytest --cov=app --cov-report= --cov-fail-under=0
    uv run pytest -m integration --cov=app --cov-append --cov-report= --cov-fail-under=0
    uv run coverage report
    bash scripts/check-coverage-targets.sh

# Contract tests contra los upstreams reales (red; el de AEMET necesita AEMET_API_KEY)
contract:
    uv run pytest -m contract -v

# Linters y contratos de arquitectura, como en CI
lint:
    uv run ruff check .
    uv run ruff format --check .
    uv run mypy app
    uv run lint-imports

# Aplica los fixes automaticos y el formato de ruff
fmt:
    uv run ruff check --fix .
    uv run ruff format .

# Auditoria de dependencias y politica de licencias, como en CI
audit:
    uv run pip-audit
    uv run pip-licenses --fail-on 'GPL;AGPL;LGPL'
