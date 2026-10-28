"""Top-level API router. Every JSON route is served under `/api`."""

from fastapi import APIRouter

from app.blueprint.routes import router as blueprint_router
from app.initiatives.routes import router as initiatives_router

api_router = APIRouter(prefix="/api")

api_router.include_router(blueprint_router)
api_router.include_router(initiatives_router)
