import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1 import v1_router
from app.core import db_registry as _db_registry  # noqa: F401 - registra modelos y handlers
from app.core.config import settings
from app.core.db import engine
from app.core.events.worker import OutboxWorker
from app.core.exceptions.handlers import register_exception_handlers
from app.core.jobs.worker import JobWorker
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
