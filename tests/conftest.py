import os

# El rate limiting (slowapi) mantiene contadores en memoria a nivel de proceso:
# entre tests se acumularian peticiones y algun test que dispara varias
# llamadas podria dar 429 de forma no determinista. Se desactiva para toda la
# suite ANTES de que se importe app.core.config (el singleton `settings` lee el
# entorno al construirse). El wiring del limiter se prueba de forma aislada en
# tests/unit/core/test_rate_limit.py, que monta su propio limiter habilitado.
os.environ.setdefault("RATE_LIMIT_ENABLED", "false")
