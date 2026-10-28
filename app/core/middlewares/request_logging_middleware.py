import time
from uuid import uuid4

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.logging import LogEvents, logger
from version import get_version_header


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Logs every request with a trace id and stamps X-Trace-ID / X-Api-Version."""

    async def dispatch(self, request: Request, call_next):
        start = time.perf_counter()
        trace_id = request.headers.get("x-trace-id") or str(uuid4())
        logger.debug(
            "%s %s %s", LogEvents.REQUEST_STARTED, request.method, request.url.path
        )
        response = await call_next(request)
        duration_ms = round((time.perf_counter() - start) * 1000, 2)
        logger.debug(
            "%s %s %s %s %sms",
            LogEvents.REQUEST_ENDED,
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
        )
        response.headers.update(
            {"X-Trace-ID": trace_id, "X-Api-Version": get_version_header()}
        )
        return response
