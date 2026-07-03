# syntax=docker/dockerfile:1.7

# --- Builder ---------------------------------------------------
FROM python:3.14-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /build

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Solo el lockfile: el venv se resuelve sin el codigo del proyecto para
# aprovechar la cache de capas cuando solo cambia app/.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# --- Runtime ---------------------------------------------------
FROM python:3.14-slim AS runtime

# TZ=UTC: las ventanas de validez de los avisos se comparan con now() y la app
# valida el TZ del proceso en el arranque.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=UTC \
    PATH="/build/.venv/bin:$PATH" \
    PYTHONPATH=/app

WORKDIR /app

RUN apt-get update \
 && apt-get upgrade -y \
 && rm -rf /var/lib/apt/lists/* \
 && python -m pip uninstall -y pip setuptools wheel

COPY --from=builder /build/.venv /build/.venv
# app importable via PYTHONPATH=/app (no se instala el proyecto en el venv).
COPY . .

RUN groupadd -g 1000 appgroup \
 && useradd -u 1000 -g appgroup -s /usr/sbin/nologin appuser \
 && chown -R appuser:appgroup /app \
 # Mountpoint del volumen de datos: el volumen nombrado copia esta propiedad
 # en su primer uso, y el check de arranque exige DATA_DIR escribible.
 && mkdir -p /data/exports \
 && chown -R appuser:appgroup /data

USER appuser
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/v1/health/liveness')" || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
