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

# Snapshot pre-migracion (ADR-0018, D5): punto de rollback si una migracion
# escribe mal. Solo BD, rapido. No debe abortar el deploy si falla.
BACKUP_DIR="${BACKUP_DIR:-/srv/geohazard-backups}"
if docker ps --format '{{.Names}}' | grep -qx geohazard-db \
   && mkdir -p "$BACKUP_DIR/pre-migrate" 2>/dev/null; then
  DB_USER="$(grep -E '^DB_USER=' .env | cut -d= -f2-)"
  DB_NAME="$(grep -E '^DB_NAME=' .env | cut -d= -f2-)"
  ts="$(date +%Y%m%dT%H%M%S)"
  if docker exec geohazard-db pg_dump -U "$DB_USER" -d "$DB_NAME" \
       --no-owner --no-acl --clean --if-exists \
       | gzip > "$BACKUP_DIR/pre-migrate/pre-migrate-$ts.sql.gz"; then
    log "snapshot pre-migracion ok"
  else
    log "WARN: snapshot pre-migracion fallo; continuo"
  fi
  # Retencion: los 5 ultimos.
  ls -1t "$BACKUP_DIR/pre-migrate/"*.sql.gz 2>/dev/null | tail -n +6 | xargs -r rm -f
else
  log "sin snapshot pre-migracion (db no arrancada o BACKUP_DIR no escribible)"
fi

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
