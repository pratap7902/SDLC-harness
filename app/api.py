"""Top-level API router. Every JSON route is served under `/api`."""

from fastapi import APIRouter, Depends

from app.auth.dependencies import get_actor
from app.blueprint.routes import router as blueprint_router
from app.initiatives.routes import router as initiatives_router

# Every /api route authenticates (token mode: 401 without a valid bearer token).
api_router = APIRouter(prefix="/api", dependencies=[Depends(get_actor)])

api_router.include_router(blueprint_router)
api_router.include_router(initiatives_router)
