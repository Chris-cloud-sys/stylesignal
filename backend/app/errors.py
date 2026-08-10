"""Consistent error envelope — spec §6.

Every non-2xx response from the API is::

    {"error": {"code": "string", "message": "human readable", "details": {}}}
"""
from typing import Any, Dict, Optional

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


class APIError(Exception):
    """Raise this anywhere in the request path to produce the §6 envelope."""

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details or {}


def error_response(
    status_code: int,
    code: str,
    message: str,
    details: Optional[Dict[str, Any]] = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {"code": code, "message": message, "details": details or {}}
        },
    )


# --- Common shorthands -----------------------------------------------------
def not_found(resource: str = "resource") -> APIError:
    return APIError(
        status.HTTP_404_NOT_FOUND, "not_found", "{0} not found".format(resource)
    )


def forbidden(message: str = "Not permitted") -> APIError:
    return APIError(status.HTTP_403_FORBIDDEN, "forbidden", message)


def unauthorized(message: str = "Invalid or expired credentials") -> APIError:
    return APIError(status.HTTP_401_UNAUTHORIZED, "unauthorized", message)


def bad_request(
    code: str, message: str, details: Optional[Dict[str, Any]] = None
) -> APIError:
    return APIError(status.HTTP_400_BAD_REQUEST, code, message, details)


def quota_exceeded(message: str, details: Dict[str, Any]) -> APIError:
    return APIError(
        status.HTTP_402_PAYMENT_REQUIRED, "quota_exceeded", message, details
    )


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(APIError)
    async def _api_error(_request: Request, exc: APIError) -> JSONResponse:
        return error_response(exc.status_code, exc.code, exc.message, exc.details)

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(
        _request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        code = {
            401: "unauthorized",
            403: "forbidden",
            404: "not_found",
            405: "method_not_allowed",
            413: "payload_too_large",
            429: "rate_limited",
        }.get(exc.status_code, "http_error")
        return error_response(exc.status_code, code, str(exc.detail))

    @app.exception_handler(RequestValidationError)
    async def _validation_error(
        _request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return error_response(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "validation_error",
            "Request failed validation",
            {"errors": _jsonable_errors(exc)},
        )

    @app.exception_handler(Exception)
    async def _unhandled(_request: Request, _exc: Exception) -> JSONResponse:
        # Deliberately opaque: internals never reach the client.
        return error_response(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "internal_error",
            "Something went wrong on our end.",
        )


def _jsonable_errors(exc: RequestValidationError):
    """Strip non-serialisable ``ctx`` payloads pydantic sometimes attaches."""
    cleaned = []
    for err in exc.errors():
        item = {k: v for k, v in err.items() if k != "ctx"}
        item["loc"] = [str(part) for part in item.get("loc", [])]
        cleaned.append(item)
    return cleaned
