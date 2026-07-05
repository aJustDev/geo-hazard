#!/usr/bin/env bash
# Restore de un dump de geo-hazard (ADR-0018). Un backup no probado no es un
# backup: este script hace el round-trip repetible.
#
#   restore.sh <dump.sql.zst|.sql.gz|.sql> [DATABASE_URL]
#
# Sin DATABASE_URL: levanta un PostGIS THROWAWAY, restaura dentro, imprime los
# recuentos de hazard_events por fuente y lo destruye. Es el test de restore.
#
# Con DATABASE_URL: restaura en ese destino. Si NO es local (throwaway), exige
# RESTORE_CONFIRM=1 para no pisar prod por un fat-finger.
set -euo pipefail

DUMP="${1:?uso: restore.sh <dump.sql.zst|.sql.gz|.sql> [DATABASE_URL]}"
TARGET_URL="${2:-}"
[ -f "$DUMP" ] || { echo "no existe el dump: $DUMP" >&2; exit 1; }

log() { echo "[restore $(date -Iseconds)] $*"; }

decompress() {
  case "$DUMP" in
    *.zst) zstd -dc "$DUMP" ;;
    *.gz)  gzip -dc "$DUMP" ;;
    *.sql) cat "$DUMP" ;;
    *) echo "extension no reconocida: $DUMP" >&2; exit 2 ;;
  esac
}

counts_sql="SELECT source, count(*) FROM hazard_events GROUP BY source ORDER BY source;"

if [ -n "$TARGET_URL" ]; then
  # Destino explicito. Guard contra prod salvo confirmacion.
  case "$TARGET_URL" in
    *@localhost*|*@127.0.0.1*) : ;;
    *) [ "${RESTORE_CONFIRM:-}" = "1" ] || {
         echo "destino no-local; re-lanza con RESTORE_CONFIRM=1 si es intencionado" >&2
         exit 3
       } ;;
  esac
  log "restaurando en $TARGET_URL"
  decompress | psql -v ON_ERROR_STOP=1 "$TARGET_URL" >/dev/null
  log "recuentos por fuente:"
  psql -At "$TARGET_URL" -c "$counts_sql"
  exit 0
fi

# Throwaway: PostGIS efimero, restaura, cuenta, destruye.
IMAGE="postgis/postgis:17-3.5"
NAME="geohazard-restore-test-$$"
cleanup() { docker rm -f "$NAME" >/dev/null 2>&1 || true; }
trap cleanup EXIT

log "levantando throwaway $NAME ($IMAGE)"
docker run -d --name "$NAME" \
  -e POSTGRES_USER=restore -e POSTGRES_PASSWORD=restore -e POSTGRES_DB=restore \
  "$IMAGE" >/dev/null

# El entrypoint de postgis arranca en dos fases: primero un servidor temporal
# que escucha SOLO por socket unix (aplica los init scripts) y luego el real
# por TCP. Forzando -h 127.0.0.1 solo damos por listo el server real y evitamos
# restaurar contra el temporal (que muere a mitad -> SIGKILL de la conexion).
log "esperando a que este listo"
for _ in $(seq 1 60); do
  docker exec "$NAME" pg_isready -h 127.0.0.1 -U restore -d restore >/dev/null 2>&1 && break
  sleep 1
done
docker exec "$NAME" pg_isready -h 127.0.0.1 -U restore -d restore >/dev/null 2>&1 \
  || { echo "el throwaway no arranco" >&2; exit 4; }

log "restaurando $DUMP"
decompress | docker exec -i "$NAME" psql -h 127.0.0.1 -v ON_ERROR_STOP=1 -U restore -d restore >/dev/null

log "recuentos por fuente tras el restore:"
docker exec "$NAME" psql -h 127.0.0.1 -U restore -d restore -At -c "$counts_sql"
log "round-trip ok"
