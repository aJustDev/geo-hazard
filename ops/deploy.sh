#!/usr/bin/env bash
# Deploy de geo-hazard en produccion (push-to-deploy via GitHub Actions).
# Disparado por la clave SSH restringida (command= forzado en authorized_keys).
# Fuente de verdad de este script: ops/deploy.sh en el repo; en el servidor se
# instala como /usr/local/bin/deploy_geohazard en el aprovisionamiento.
set -euo pipefail

APP_DIR=/opt/geohazard
COMPOSE="docker compose -f compose.yml"

log() { echo "[deploy_geohazard $(date -Iseconds)] $*"; }

cd "$APP_DIR"

log "fetch + reset -> origin/main"
git fetch origin main
git reset --hard origin/main

log "build images"
$COMPOSE build api migrate

log "run migrations (bloqueante)"
$COMPOSE run --rm migrate

log "up api"
$COMPOSE up -d api

log "smoke local"
for i in 1 2 3 4 5 6 7 8 9 10; do
  if curl -fsS -o /dev/null http://127.0.0.1:8002/v1/health/liveness; then
    log "api healthy en intento $i"
    exit 0
  fi
  sleep 3
done

log "ERROR: api no respondio en 30s"
$COMPOSE logs --tail=80 api
exit 1
