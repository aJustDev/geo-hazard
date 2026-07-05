#!/usr/bin/env bash
# Backup diario de geo-hazard (ADR-0018). Dos piezas independientes:
#   1) dump logico de la BD (pg_dump | zstd|gzip): reconstruye hazard_events y
#      todo el estado transaccional (outbox, jobs, sync_state).
#   2) copia del volumen de datos (snapshots GeoParquet): es el unico activo
#      IRREPRODUCIBLE; los upstreams solo sirven ventanas rodantes (ADR-0007).
# Retencion: 7 diarios + 4 semanales (el semanal se puebla los domingos).
# Destino: local. El offsite (restic) esta pospuesto; ver el hueco marcado
# abajo (HOOK offsite). Cubre "migracion mala" y corrupcion de volumen, NO la
# perdida del VPS entero (riesgo aceptado, ADR-0018).
#
# Config por entorno (todo con defaults de produccion):
#   BACKUP_DIR    destino, FUERA del checkout (git reset --hard no lo toca)
#   ENV_FILE      .env de runtime del que se leen DB_USER/DB_NAME
#   DB_CONTAINER  contenedor de Postgres
#   DATA_VOLUME   volumen Docker con los GeoParquet
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/geohazard}"
ENV_FILE="${ENV_FILE:-$APP_DIR/.env}"
BACKUP_DIR="${BACKUP_DIR:-/srv/geohazard-backups}"
DB_CONTAINER="${DB_CONTAINER:-geohazard-db}"
DATA_VOLUME="${DATA_VOLUME:-geohazard_geohazard_data}"

log() { echo "[backup $(date -Iseconds)] $*"; }
die() { log "ERROR: $*"; exit 1; }

# DB_USER/DB_NAME salen del .env de runtime (nunca viven en el repo). Se pueden
# forzar por entorno para el test local contra la BD de desarrollo.
read_env() {
  local key="$1" val
  [ -f "$ENV_FILE" ] || return 0
  val="$(grep -E "^${key}=" "$ENV_FILE" | tail -n1 | cut -d= -f2-)"
  val="${val%\"}"; val="${val#\"}"
  printf '%s' "$val"
}
DB_USER="${DB_USER:-$(read_env DB_USER)}"
DB_NAME="${DB_NAME:-$(read_env DB_NAME)}"
[ -n "$DB_USER" ] || die "DB_USER no resuelto (revisa $ENV_FILE o exporta DB_USER)"
[ -n "$DB_NAME" ] || die "DB_NAME no resuelto (revisa $ENV_FILE o exporta DB_NAME)"

# Compresor: zstd si esta (mejor ratio), gzip como fallback universal.
if command -v zstd >/dev/null 2>&1; then
  COMPRESS=(zstd -q -T0); EXT="zst"
else
  COMPRESS=(gzip); EXT="gz"
fi

STAMP="$(date +%Y-%m-%d)"
DAILY="$BACKUP_DIR/daily"
WEEKLY="$BACKUP_DIR/weekly"
mkdir -p "$DAILY" "$WEEKLY"

docker inspect "$DB_CONTAINER" >/dev/null 2>&1 || die "contenedor $DB_CONTAINER no existe"

# 1) Dump logico. --no-owner/--no-acl: el arbol tiene un solo rol de app, asi
# el restore es portable a cualquier destino. --clean/--if-exists: restaurable
# sobre una BD ya poblada de forma idempotente.
db_out="$DAILY/geohazard-${STAMP}.sql.${EXT}"
log "pg_dump $DB_NAME -> $db_out"
docker exec "$DB_CONTAINER" pg_dump -U "$DB_USER" -d "$DB_NAME" \
  --no-owner --no-acl --clean --if-exists \
  | "${COMPRESS[@]}" > "$db_out"
[ -s "$db_out" ] || die "el dump quedo vacio: $db_out"

# 2) Copia del volumen de datos (GeoParquet). tar a stdout para que el fichero
# lo escriba el usuario del host, no root del contenedor.
data_out="$DAILY/geohazard-data-${STAMP}.tar.gz"
if docker volume inspect "$DATA_VOLUME" >/dev/null 2>&1; then
  log "tar volumen $DATA_VOLUME -> $data_out"
  docker run --rm -v "${DATA_VOLUME}:/data:ro" alpine \
    tar czf - -C /data . > "$data_out"
else
  log "WARN: volumen $DATA_VOLUME no existe; omito copia de datos (dev sin volumen)"
fi

# Semanal: los domingos, promociona el diario de hoy a weekly/.
if [ "$(date +%u)" = "7" ]; then
  log "domingo: promociono a weekly/"
  cp -f "$db_out" "$WEEKLY/"
  [ -f "$data_out" ] && cp -f "$data_out" "$WEEKLY/"
fi

# Retencion por antiguedad: 7 dias en daily, 28 en weekly.
find "$DAILY" -type f -name 'geohazard-*' -mtime +7 -delete
find "$WEEKLY" -type f -name 'geohazard-*' -mtime +28 -delete

# HOOK offsite (pospuesto, ADR-0018): cuando se elija destino, empujar aqui el
# diario recien creado con restic, p.ej.:
#   restic -r "$RESTIC_REPO" backup "$db_out" "$data_out"
# El resto del script no cambia; el offsite es aditivo.

log "backup ok: $(du -sh "$BACKUP_DIR" | cut -f1) en $BACKUP_DIR"
