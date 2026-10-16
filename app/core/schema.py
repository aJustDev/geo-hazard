from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class BaseSchema(BaseModel):
    """Base for all DTOs. `from_attributes` lets routers do
    `ReadSchema.model_validate(orm_object)`."""

    model_config = ConfigDict(from_attributes=True)


class ErrorResponse(BaseSchema):
    """Envelope homogeneo de error (app/core/exceptions/handlers.py)."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "detail": "clusters requires a bounding filter: bbox or starts_after",
                    "code": "business_validation",
                }
            ]
        }
    )

    detail: str = Field(description="Human-readable message.")
    code: str = Field(description="Stable machine-readable error code.")
    errors: list[dict[str, Any]] | None = Field(
        default=None, description="Per-parameter details (422 only)."
    )


_ERROR_DESCRIPTIONS = {
    400: "Invalid filter (business rule), e.g. malformed bbox or cursor.",
    404: "Not found.",
    422: "Invalid query or path parameters.",
    429: "Rate limit exceeded. Honor the Retry-After header.",
    503: "Analytics plane saturated. Honor the Retry-After header.",
}


def error_responses(*status_codes: int) -> dict[int | str, dict[str, Any]]:
    """`responses=` de FastAPI para documentar los errores con el envelope real
    (sin esto, /docs anuncia el 422 por defecto de FastAPI, que no servimos)."""
    return {
        code: {"model": ErrorResponse, "description": _ERROR_DESCRIPTIONS[code]}
        for code in status_codes
    }
