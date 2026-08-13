#!/usr/bin/env bash
# Alerta de frescura de fuentes (ADR-0019). Consulta /v1/sources/status y avisa
# por notify-cartagena.sh (ntfy + Telegram) cuando el estado CAMBIA: al
# degradarse, al cambiar las fuentes afectadas y al recuperarse. Un episodio
# que sigue abierto se recuerda una vez al dia. Pensado para cron cada 15-30
# min. CALLADO cuando todo va bien.
#
# Por que solo en los cambios: entre el 6/7 y el 8/8 de 2026 esta alerta
# genero 571 mensajes que eran 26 episodios reales. El desglose importa,
# porque no es lo que parece: aemet se degrado 16 veces y effis solo 8, pero
# las de effis duraron 56h, 32h y 24h, y cada una mandaba un aviso cada 20
# minutos. Encima iban a `mail` local, que en cartagena no sale de la maquina
# (exim4 en modo local, sin smarthost), asi que no los leyo nadie.
#
# Severidad por fuente: aemet e ign alimentan avisos meteorologicos y sismos;
# effis es analitica de area quemada contra un MapServer que ADR-0015 ya da
# por intermitente por diseno (responde 500 durante horas y se reintenta en el
# siguiente ciclo, sin corromper nada), asi que baja a prioridad informativa.
#
# Limitacion conocida (ADR-0019): si el host entero cae no hay quien avise. Lo
# cubre el dead-man externo de healthchecks.io (ductual-healthcheck.timer).
#
# Config por entorno:
#   SOURCES_STATUS_URL   endpoint a consultar
#   SOURCES_STATE_FILE   donde se recuerda el ultimo estado avisado
#   SOURCES_REMINDER_S   segundos entre recordatorios de un episodio abierto
set -euo pipefail

URL="${SOURCES_STATUS_URL:-http://127.0.0.1:8002/v1/sources/status}"
ESTADO="${SOURCES_STATE_FILE:-$HOME/.local/state/geohazard-sources.state}"
RECORDATORIO="${SOURCES_REMINDER_S:-86400}"
HOST="$(hostname)"

mkdir -p "$(dirname "$ESTADO")"

# prioridad asunto cuerpo
avisar() {
  if command -v notify-cartagena.sh >/dev/null 2>&1 &&
    NOTIFY_PRIORITY="$1" NOTIFY_TAGS=satellite notify-cartagena.sh "$2" "$3"; then
    return 0
  fi
  # Sin notificador, o si el envio falla: al menos deja rastro en el cron.
  echo "[check-sources] $2 :: $3" >&2
}

# La API responde 200 aun degradada; -f solo captura caidas reales (conn/5xx).
if body="$(curl -fsS --max-time 10 "$URL" 2>/dev/null)"; then
  status="$(printf '%s' "$body" | jq -r '.status // "desconocido"')"
  firma="$(printf '%s' "$body" |
    jq -r '[.sources[] | select(.healthy | not) | .source] | sort | join(",")')"
  detalle="$(printf '%s' "$body" | jq -r '
    .sources[] | select(.healthy | not)
    | "\(.source): sin exito desde hace \(((.seconds_since_success // 0) / 360 | round) / 10)h"
      + " (cadencia \((.interval_seconds // 0) / 60 | round)min,"
      + " \(.consecutive_failures) fallos seguidos, stale=\(.stale))"')"
  [ "$status" = "ok" ] && firma="ok"
  [ -n "$firma" ] || firma="desconocido"
else
  firma="api-caida"
  detalle="$URL no responde (conexion o 5xx)."
fi

# Estado anterior: "<firma> <epoch del ultimo aviso>". Los chequeos silenciados
# NO lo reescriben: asi el epoch marca el ultimo aviso, no el ultimo chequeo.
anterior="ok"
visto=0
if [ -r "$ESTADO" ]; then
  read -r anterior visto <"$ESTADO" || true
  : "${anterior:=ok}"
  : "${visto:=0}"
fi

ahora="$(date +%s)"
recordatorio=0

if [ "$firma" = "$anterior" ]; then
  [ "$firma" = "ok" ] && exit 0
  [ $((ahora - visto)) -lt "$RECORDATORIO" ] && exit 0
  recordatorio=1
fi

if [ "$firma" = "ok" ]; then
  avisar 2 "geohazard: fuentes recuperadas en $HOST" \
    "Las fuentes vuelven a estar sanas. Estaba degradado: $anterior."
else
  case "$firma" in
    api-caida) prio=5 ;;
    *aemet* | *ign*) prio=4 ;;
    *) prio=3 ;; # solo effis: intermitente por diseno (ADR-0015)
  esac
  if [ "$firma" = "api-caida" ]; then
    asunto="geohazard: la API no responde en $HOST"
    [ "$recordatorio" = 1 ] && asunto="geohazard: la API sigue sin responder en $HOST"
  else
    asunto="geohazard: fuentes degradadas ($firma) en $HOST"
    [ "$recordatorio" = 1 ] && asunto="geohazard: $firma sigue degradada en $HOST"
  fi
  avisar "$prio" "$asunto" "$detalle"
fi

printf '%s %s\n' "$firma" "$ahora" >"$ESTADO"
