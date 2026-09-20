"""Only deliberate, public messages may cross the HTTP error boundary."""

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str):
        self.status, self.code, self.message = status, code, message
        super().__init__(code)


def error_response(status: int, code: str, message: str) -> JSONResponse:
    headers = {"Cache-Control": "no-store"}
    if status == 401:
        headers["WWW-Authenticate"] = "Bearer"
    if status == 429:
        headers["Retry-After"] = "60"
    return JSONResponse(status_code=status, content={"detail": message, "code": code}, headers=headers)


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def api_error(_request: Request, exc: ApiError):
        return error_response(exc.status, exc.code, exc.message)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_request: Request, _exc: RequestValidationError):
        # Pydantic errors can contain the original input, including document text.
        return error_response(422, "invalid_request", "The request contains invalid or missing fields.")

    @app.exception_handler(HTTPException)
    async def http_error(_request: Request, exc: HTTPException):
        return error_response(exc.status_code, "http_error", "The request could not be completed.")

    @app.exception_handler(Exception)
    async def unexpected_error(_request: Request, _exc: Exception):
        return error_response(500, "internal_error", "Scanner could not complete this request.")
