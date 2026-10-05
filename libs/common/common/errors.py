import logging
from typing import Any, Optional

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from common.responses import error_response

logger = logging.getLogger(__name__)


class AppError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        status_code: int = 400,
        details: Any = None,
        headers: Optional[dict] = None,
    ):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details
        self.headers = headers


class BadRequestError(AppError):
    def __init__(self, message: str, details: Any = None):
        super().__init__("BAD_REQUEST", message, 400, details)


class UnauthorizedError(AppError):
    def __init__(self, message: str = "Authentication required"):
        super().__init__("UNAUTHORIZED", message, 401, headers={"WWW-Authenticate": "Bearer"})


class ForbiddenError(AppError):
    def __init__(self, message: str = "You do not have access to this resource"):
        super().__init__("FORBIDDEN", message, 403)


class NotFoundError(AppError):
    def __init__(self, resource: str):
        super().__init__("NOT_FOUND", f"{resource} not found", 404)


class ConflictError(AppError):
    def __init__(self, message: str):
        super().__init__("CONFLICT", message, 409)


class UnprocessableError(AppError):
    def __init__(self, message: str, details: Any = None):
        super().__init__("UNPROCESSABLE", message, 422, details)


class ServiceUnavailableError(AppError):
    def __init__(self, message: str = "Service temporarily unavailable"):
        super().__init__("SERVICE_UNAVAILABLE", message, 503)


class RateLimitExceeded(AppError):
    def __init__(self, retry_after_seconds: int, message: str = "Too many requests, please try again later"):
        retry_after = max(1, int(retry_after_seconds))
        super().__init__(
            "RATE_LIMITED",
            message,
            429,
            {"retry_after_seconds": retry_after},
            {"Retry-After": str(retry_after)},
        )


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def handle_app_error(_: Request, error: AppError):
        return error_response(error.code, error.message, error.status_code, error.details, error.headers)

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(_: Request, error: RequestValidationError):
        issues = [
            {
                "field": ".".join(str(part) for part in item["loc"][1:]) or str(item["loc"][0]),
                "issue": item["msg"],
            }
            for item in error.errors()
        ]
        return error_response("VALIDATION_ERROR", "Invalid request data", 422, issues)

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_error(_: Request, error: StarletteHTTPException):
        return error_response(
            f"HTTP_{error.status_code}",
            str(error.detail),
            error.status_code,
            headers=getattr(error, "headers", None),
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, error: Exception):
        logger.exception("Unhandled error on %s %s", request.method, request.url.path)
        return error_response("INTERNAL_ERROR", "Something went wrong", 500)
