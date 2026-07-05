#!/usr/bin/env bash
# Alerta de frescura de fuentes (ADR-0019). Consulta /v1/sources/status y, si
# algo no esta sano (o la API no responde), manda un mail local. Pensado para
# cron cada 15-30 min. CALLADO cuando todo va bien: un cron que spamea se acaba
# ignorando.
#
# Limitacion conocida (ADR-0019): si el host entero cae, no hay quien mande el
# mail. Se acepta ahora; el hueco se cierra con un dead-man externo (fuera de
# scope de esta fase).
#
# Config por entorno:
#   SOURCES_STATUS_URL  endpoint a consultar (default: la API local via Caddy-less)
#   ALERT_MAILTO        destinatario (default: root; alias en /etc/aliases)
set -euo pipefail

URL="${SOURCES_STATUS_URL:-http://127.0.0.1:8002/v1/sources/status}"
MAILTO="${ALERT_MAILTO:-root}"
HOST="$(hostname)"

send_mail() {
  local subject="$1" msg="$2"
  if command -v mail >/dev/null 2>&1; then
    printf '%s\n' "$msg" | mail -s "$subject" "$MAILTO"
  else
    # Sin MTA: al menos deja rastro en el log del cron / journal.
    echo "[check-sources] (sin 'mail') $subject :: $msg" >&2
  fi
}

# La API responde 200 aun degradada; -f solo captura caidas reales (conn/5xx).
if ! body="$(curl -fsS --max-time 10 "$URL" 2>/dev/null)"; then
  send_mail "[geohazard] alerta: API no responde en $HOST" \
    "geohazard: $URL no responde (conexion o 5xx)."
  exit 0
fi

# status de nivel superior: aparece una sola vez (las fuentes usan healthy/stale).
status="$(printf '%s' "$body" \
  | grep -o '"status"[[:space:]]*:[[:space:]]*"[^"]*"' \
  | head -1 \
  | sed 's/.*"\([^"]*\)"$/\1/')"

if [ "$status" != "ok" ]; then
  send_mail "[geohazard] fuentes degradadas en $HOST" \
    "$(printf 'geohazard: estado de fuentes no OK (status=%s) en %s\n\n%s' \
        "${status:-desconocido}" "$HOST" "$body")"
fi
