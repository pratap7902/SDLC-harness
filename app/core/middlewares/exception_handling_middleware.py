from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.exception_handlers import custom_exception_handler


class ExceptionHandlingMiddleware(BaseHTTPMiddleware):
    """Middleware for handling exceptions"""

    async def dispatch(self, request: Request, call_next):
        try:
            return await call_next(request)
        except Exception as e:
            return custom_exception_handler(request, e)
