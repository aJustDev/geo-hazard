import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError

from app.core.exceptions.exceptions import DomainException

logger = logging.getLogger(__name__)


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(DomainException)
    async def _domain(_: Request, exc: DomainException) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.message, "code": exc.code},
        )

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "detail": "Validation error",
                "code": "validation_error",
                "errors": exc.errors(),
            },
        )

    @app.exception_handler(IntegrityError)
    async def _integrity(_: Request, exc: IntegrityError) -> JSONResponse:
        # Safety net for UNIQUE/FK races that slip past use_case pre-checks.
        logger.warning("IntegrityError surfaced to handler: %s", exc)
        return JSONResponse(
            status_code=409,
            content={"detail": "Integrity conflict", "code": "integrity_conflict"},
        )
