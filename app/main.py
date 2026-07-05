import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.api.v1 import v1_router
from app.core import db_registry as _db_registry  # noqa: F401 - registra modelos y handlers
from app.core.config import settings
from app.core.db import engine
from app.core.events.worker import OutboxWorker
from app.core.exceptions.handlers import register_exception_handlers
from app.core.jobs.worker import JobWorker
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
if settings.cors_origins:
    # Solo lectura desde el front estatico: GET (el middleware gestiona el preflight).
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET"],
        allow_headers=["*"],
    )
register_exception_handlers(app)
app.include_router(v1_router)
