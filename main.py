import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api import api_router
from app.core.exception_handlers import register_exception_handlers
from app.core.logging import LogEvents, logger
from app.core.middlewares.exception_handling_middleware import (
    ExceptionHandlingMiddleware,
)
from app.core.middlewares.request_logging_middleware import RequestLoggingMiddleware
from app.mcp.server import mcp
from app.web.rendering import STATIC_DIR
from app.web.spa import router as spa_router
from config.settings import settings

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")

mcp.settings.streamable_http_path = "/mcp"
mcp_app = mcp.streamable_http_app()


def _sentry() -> None:
    if not settings.app.SENTRY_DSN:
        return
    import sentry_sdk

    sentry_sdk.init(dsn=settings.app.SENTRY_DSN, environment=settings.app.APP_ENV)


@asynccontextmanager
async def lifespan(_: FastAPI):
    """A lifespan (not `on_event`) because the MCP session manager has to stay open for as
    long as the app serves requests."""
    _sentry()
    async with mcp.session_manager.run():
        yield


app = FastAPI(
    title="SDLC Record Service",
    description="System of record for the automated SDLC pipeline: typed records under one "
    "validated write path, derived statuses and gates, a worklist, and the drift report.",
    version="0.1.0",
    lifespan=lifespan,
)

register_exception_handlers(app)

app.add_middleware(ExceptionHandlingMiddleware)
app.add_middleware(RequestLoggingMiddleware)
# The Vite dev server (http://localhost:5173) calls the API cross-origin.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.app.cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Trace-ID", "X-Api-Version"],
)

app.include_router(api_router)
app.include_router(spa_router)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/health")
def health():
    """Infrastructure health check."""
    logger.debug(LogEvents.HEALTH_CHECK)
    return {"status": "healthy"}


# Agent interface at /mcp (streamable HTTP). Mounted last: a root mount would otherwise
# shadow every route above.
app.mount("/", mcp_app)
