#!/usr/bin/env bash
# Basemap del front (ADR-0022): extracto de Espana del build diario de
# Protomaps, mas las fuentes y sprites que pide el estilo. Se ejecuta en la
# maquina de desarrollo (cartagena no tiene la CLI pmtiles) y se sube con
# rsync; ver docs/deploy.md, seccion "Basemap".
#
# Uso: scripts/build_basemap.sh <directorio_salida>   (fuera del repo)
# Deja <salida>/basemap/spain-<YYYYMMDD>.pmtiles y <salida>/assets/.
set -euo pipefail

OUT="${1:?uso: $0 <directorio_salida>}"
REGION="$(dirname "$0")/../deploy/basemap-region.geojson"
MAXZOOM=12
BUILD_URL="https://build.protomaps.com"
ASSETS_URL="https://github.com/protomaps/basemaps-assets/archive/refs/heads/main.tar.gz"

command -v pmtiles >/dev/null || { echo "ERROR: falta la CLI pmtiles (go-pmtiles)" >&2; exit 1; }

# Los builds no tienen alias "latest" y se guardan una semana: se busca el mas
# reciente con una peticion Range de un byte por dia hacia atras.
build=""
for offset in $(seq 0 9); do
  stamp="$(date -u -d "-${offset} day" +%Y%m%d)"
  if curl --silent --fail --max-time 10 --range 0-0 --output /dev/null "${BUILD_URL}/${stamp}.pmtiles"; then
    build="$stamp"
    break
  fi
done
[ -n "$build" ] || { echo "ERROR: ningun build en ${BUILD_URL} en los ultimos 10 dias" >&2; exit 1; }

# Nombre versionado: Caddy lo sirve con cache immutable.
target="${OUT}/basemap/spain-${build}.pmtiles"
mkdir -p "${OUT}/basemap"
if [ -f "$target" ]; then
  echo "${target} ya existe"
else
  pmtiles extract "${BUILD_URL}/${build}.pmtiles" "${target}.partial" \
    --region="$REGION" --maxzoom="$MAXZOOM" --download-threads=8
  mv "${target}.partial" "$target"
fi

# Fuentes y sprites: los mismos bytes para cualquier extracto. Solo lo que
# referencia el estilo de @protomaps/basemaps.
if [ ! -d "${OUT}/assets/sprites/v4" ]; then
  staging="$(mktemp -d)"
  trap 'rm -rf "$staging"' EXIT
  curl --silent --show-error --fail --location --max-time 300 "$ASSETS_URL" \
    | tar -xz -C "$staging" --strip-components=1 \
      "basemaps-assets-main/fonts/Noto Sans Regular" \
      "basemaps-assets-main/fonts/Noto Sans Medium" \
      "basemaps-assets-main/fonts/Noto Sans Italic" \
      "basemaps-assets-main/sprites/v4"
  mkdir -p "${OUT}/assets"
  mv "${staging}/fonts" "${staging}/sprites" "${OUT}/assets/"
fi

pmtiles show "$target" | grep -E "max zoom|tile type|bounds" || true
du -sh "$target" "${OUT}/assets"
