"""
Exception handlers for the FastAPI application.

This module defines handlers for custom exceptions to ensure consistent
error responses across the API.
"""

from typing import Any, Dict, Optional

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from app.core.logging import logger
from app.exceptions.base_exception import BaseAppException


def register_exception_handlers(app: FastAPI) -> None:
    """
    Register all exception handlers with the FastAPI application.

    Args:
        app: The FastAPI application instance
    """

    @app.exception_handler(BaseAppException)
    async def handle_base_app_exception(
        request: Request, exc: BaseAppException
    ) -> JSONResponse:
        """
        Handle base application exceptions.

        Args:
            request: The request that caused the exception
            exc: The base application exception

        Returns:
            JSONResponse with formatted error details
        """
        return format_exception_response(
            status_code=exc.status_code,
            title=exc.message,
            detail=exc.message,
            instance=str(request.url),
            extra={"error_code": exc.error_code, "error_data": exc.error_data},
        )

    @app.exception_handler(RequestValidationError)
    async def handle_fastapi_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        """
        Handle FastAPI validation errors.

        Args:
            request: The request that caused the exception
            exc: The FastAPI validation error

        Returns:
            JSONResponse with formatted error details
        """
        return format_exception_response(
            status_code=422,
            title="Validation Error",
            detail="Request failed validation checks.",
            instance=str(request.url),
            extra={
                "errors": format_validation_errors(exc.errors()),
            },
        )

    @app.exception_handler(ValidationError)
    async def handle_pydantic_validation_error(
        request: Request, exc: ValidationError
    ) -> JSONResponse:
        """
        Handle Pydantic validation errors.

        Args:
            request: The request that caused the exception
            exc: The Pydantic validation error

        Returns:
            JSONResponse with formatted error details
        """
        return format_exception_response(
            status_code=422,
            title="Validation Error",
            detail="Model failed validation.",
            instance=str(request.url),
            extra={
                "errors": format_validation_errors(exc.errors()),
            },
        )

    @app.exception_handler(Exception)
    async def handle_unhandled_exception(
        request: Request, exc: Exception
    ) -> JSONResponse:
        """
        Handle unhandled exceptions.

        Args:
            request: The request that caused the exception
            exc: The unhandled exception

        Returns:
            JSONResponse with formatted error details
        """
        logger.exception("Unhandled exception")
        return format_exception_response(
            status_code=500,
            title="Internal Server Error",
            detail=str(exc),
            instance=str(request.url),
            extra={"exception_type": type(exc).__name__},
        )


def custom_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """
    Handle server-side exceptions.

    Args:
        request: The request that caused the exception
        exc: The server exception

    Returns:
        JSONResponse with formatted error details
    """
    # Log the exception
    logger.exception("Something went wrong")

    status_code = getattr(exc, "status_code", 500)
    message = getattr(exc, "message", "Something went wrong. Try again.")
    error_code = getattr(exc, "error_code", "INTERNAL_SERVER_ERROR")

    # Default server error response
    return format_exception_response(
        status_code=status_code,
        title=message,
        detail=message,
        instance=str(request.url),
        extra={
            "error_code": error_code,
            "exception_type": type(exc).__name__,
            "message": str(exc),
        },
    )


def format_exception_response(
    status_code: int,
    title: str,
    detail: Optional[str] = None,
    instance: Optional[str] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> JSONResponse:
    """
    Format a problem response for the given parameters.

    Args:
        status_code: The HTTP status code
        title: The title of the error
        detail: The detail of the error
        instance: The instance of the error
        extra: Extra data to include in the response

    Returns:
        JSONResponse with formatted error details
    """
    response = {
        "status": status_code,
        "title": title,
        "detail": detail or title,
        "instance": instance or "",
    }
    if extra:
        response.update(extra)

    # Set Content-Type header according to RFC 9457
    headers = {"Content-Type": "application/problem+json"}

    return JSONResponse(status_code=status_code, content=response, headers=headers)


def format_validation_errors(errors: list) -> list:
    """
    Format validation errors for the given list of errors.

    Args:
        errors: List of validation errors

    Returns:
        List of formatted validation errors with user-friendly titles
    """
    formatted_errors = []

    for error in errors:
        # Extract location information safely
        loc = error.get("loc", [])
        field_name = loc[-1] if loc else "field"

        # Get error message
        msg = error.get("msg", "Invalid value")

        # Create a user-friendly title using the field name and message
        title = f"Field '{field_name}' {msg.lower()}"

        # Create formatted error with only the required fields
        formatted_error = {
            "title": title,
            "loc": loc,
            "input": error.get("input", None),
        }

        formatted_errors.append(formatted_error)

    return formatted_errors
