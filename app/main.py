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


app = FastAPI(title=settings.APP_NAME, version=settings.APP_VERSION, lifespan=lifespan)

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
# listo, de valor inmediato bajo.
#
# Limitacion conocida: FastAPI 0.139 anida los routers incluidos como
# _IncludedRouter, que starlette-exporter 0.23 no sabe resolver, asi que
# group_paths NO agrupa (p.ej. /v1/events/{id} se veria por URL literal) y
# filter_unhandled_paths=True descartaria TODAS las series. Por eso va en False:
# se registran todas las peticiones, a cambio de que un escaner de 404s pueda
# crear series por path (acotado por los reinicios frecuentes y el mem_limit).
# group_paths queda en True: es inocuo hoy y se autocorrige cuando la libreria
# soporte _IncludedRouter. Revisar al desplegar un scraper real.
app.add_middleware(
    PrometheusMiddleware,
    app_name="geohazard",
    group_paths=True,
    filter_unhandled_paths=False,
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
