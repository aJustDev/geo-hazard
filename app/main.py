import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from starlette_exporter import PrometheusMiddleware, handle_metrics

from app.api.v1 import v1_router
from app.core import db_registry as _db_registry  # noqa: F401 - registra modelos y handlers
from app.core.config import settings
from app.core.db import engine
from app.core.events.worker import OutboxWorker
from app.core.exceptions.handlers import register_exception_handlers
from app.core.jobs.worker import JobWorker
from app.core.logging import RequestIdMiddleware
from app.core.rate_limit import limiter, rate_limit_exceeded_handler
from app.core.startup import check_data_dir, check_database, check_utc_timezone

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    check_utc_timezone()
    check_data_dir()
    db_status = await check_database(engine)
    app.state.ready = db_status == "OK"

    # Los workers se construyen siempre (para poder pararlos en shutdown) pero
    # solo arrancan si la BD esta disponible.
    outbox_worker = OutboxWorker()
    job_worker = JobWorker()
    if app.state.ready:
        await outbox_worker.start()
        await job_worker.start()
    app.state.outbox_worker = outbox_worker
    app.state.job_worker = job_worker

    yield

    await job_worker.stop()
    await outbox_worker.stop()
    app.state.ready = False
    await engine.dispose()


_REPO = "https://github.com/aJustDev/geo-hazard"

# Texto publico de /docs: en ingles, como el README y los ADRs.
_DESCRIPTION = f"""
Natural-hazard spatial API for the Iberian Peninsula, built on open European
data: wildfires from Copernicus EFFIS, earthquakes from the Spanish IGN and
severe-weather warnings from AEMET, normalized into one model with a common
1-4 severity scale.

- Event endpoints return GeoJSON (RFC 7946) in EPSG:4326, lon/lat order.
- Public and unauthenticated (open data). Rate limited per IP; the
  analytics and clustering endpoints have a stricter quota. A `429` or `503`
  carries `Retry-After`.
- Errors use one envelope: `{{"detail", "code"}}`.
- Data attribution: every response carries an `attribution` member with the
  credit each source requires. Terms per source are in
  [NOTICE]({_REPO}/blob/main/NOTICE). This project is not affiliated with or
  endorsed by AEMET, IGN/CNIG or the Copernicus programme.
- Source freshness: `GET /v1/sources/status`.
"""

_TAGS = [
    {"name": "Events", "description": "Hazard events: listing, radius search, clustering."},
    {"name": "Analytics", "description": "Aggregates over the GeoParquet history (DuckDB)."},
    {"name": "Sources", "description": "Freshness and attribution of each upstream source."},
    {"name": "Health", "description": "Liveness and readiness probes."},
]

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description=_DESCRIPTION,
    license_info={"name": "MIT", "url": f"{_REPO}/blob/main/LICENSE"},
    contact={"name": "geo-hazard on GitHub", "url": _REPO},
    openapi_tags=_TAGS,
    lifespan=lifespan,
)

# Rate limiting (ADR-0017). Se anade ANTES que CORS para que este ultimo quede
# como middleware mas externo y las respuestas 429 tambien lleven cabeceras
# CORS. Los decoradores @limiter.limit de los endpoints caros funcionan aunque
# el limiter este deshabilitado (no-op); el middleware solo se monta si esta on.
if settings.RATE_LIMIT_ENABLED:
    app.state.limiter = limiter
    # Starlette tipa el handler con exc: Exception; el nuestro lo estrecha a
    # RateLimitExceeded (mas claro). Falso positivo de varianza conocido.
    app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)  # type: ignore[arg-type]
    app.add_middleware(SlowAPIMiddleware)
# Metricas Prometheus (ADR-0019). Se anade DESPUES del rate-limit para quedar
# por fuera de el y contabilizar tambien las respuestas 429. El endpoint es
# privado (Caddy lo bloquea al exterior) y hoy no hay scraper: es un enganche
# listo, de valor inmediato bajo. group_paths etiqueta por plantilla de ruta
# (/v1/events/{event_id}) y filter_unhandled_paths descarta las rutas que no
# existen, asi que un escaner de 404s no puede crear series por URL.
app.add_middleware(
    PrometheusMiddleware,
    app_name="geohazard",
    group_paths=True,
    filter_unhandled_paths=True,
    skip_paths=["/metrics"],
)
app.add_route("/metrics", handle_metrics)
if settings.cors_origins:
    # Solo lectura desde el front estatico: GET (el middleware gestiona el preflight).
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET"],
        allow_headers=["*"],
    )
# Request-id como middleware MAS EXTERNO (se anade el ultimo): fija el id antes
# de CORS y rate-limit y lo devuelve en la cabecera de toda respuesta, 429 y
# errores incluidos (ADR-0019).
app.add_middleware(RequestIdMiddleware)
register_exception_handlers(app)
app.include_router(v1_router)
