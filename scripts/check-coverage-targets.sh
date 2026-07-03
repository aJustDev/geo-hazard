#!/usr/bin/env bash
# Targets de cobertura por capa, ademas del gate global (fail_under en
# pyproject). Requiere un .coverage ya generado (unit + integration).
# Se activa en CI cuando existan use_cases/repos/services (fase IGN+AEMET).
set -euo pipefail

check() {
  local pattern="$1" target="$2"
  # "No data" tambien falla: un patron huerfano tras un refactor no debe
  # convertirse en un gate que aprueba en vacio.
  uv run coverage report --include="$pattern" --fail-under="$target" \
    || { echo "FAIL: $pattern por debajo de $target%"; exit 1; }
}

check "app/hazards/use_cases/*" 90
check "app/hazards/repos/*" 85
check "app/hazards/services/*" 85
check "app/analytics/use_cases/*" 90
check "app/analytics/queries/*" 85

echo "OK: todos los targets por modulo cumplidos"
