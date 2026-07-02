from typing import ClassVar


class DomainException(Exception):
    """Base for errors the API maps to a stable response.

    `code` is the client contract (stable string); `message` is free text.
    """

    status_code: ClassVar[int] = 500
    code: ClassVar[str] = "internal_error"

    def __init__(self, message: str | None = None) -> None:
        super().__init__(message or self.code)
        self.message = message or self.code


class NotFoundError(DomainException):
    status_code = 404
    code = "not_found"

    def __init__(self, entity: str, entity_id: object = None) -> None:
        suffix = f" (id: {entity_id})" if entity_id is not None else ""
        super().__init__(f"{entity} not found{suffix}")


class ConflictError(DomainException):
    status_code = 409
    code = "conflict"


class BusinessValidationError(DomainException):
    status_code = 400
    code = "business_validation"


class ExternalServiceError(DomainException):
    status_code = 502
    code = "external_service_error"
