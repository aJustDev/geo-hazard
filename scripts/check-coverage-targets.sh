#!/usr/bin/env bash
# Targets de cobertura por capa, ademas del gate global (fail_under en
# pyproject). Requiere un .coverage ya generado (unit + integration); CI lo
# corre tras las dos suites.
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
# El nucleo de concurrencia (outbox y jobs) es donde viven los invariantes
# mas criticos; sin target propio, un hueco alli no lo caza ningun gate.
check "app/core/events/*" 85
check "app/core/jobs/*" 85
# La frontera con los upstreams: un parser con una rama sin probar es el sitio
# donde un dato malformado tumba un lote. El 85% global lo enmascararia.
check "app/core/*/parser.py" 90
check "app/core/*/drivers/*" 85
check "app/hazards/api/*,app/analytics/api/*,app/api/*" 85

echo "OK: todos los targets por modulo cumplidos"
