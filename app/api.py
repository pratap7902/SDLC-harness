"""Top-level API router. Every JSON route is served under `/api`."""

from fastapi import APIRouter, Depends

from app.auth.dependencies import get_actor
from app.blueprint.routes import router as blueprint_router
from app.initiatives.routes import router as initiatives_router
from app.initiatives.test_run_routes import router as test_run_router
from app.registry.routes import router as registry_router

# Every /api route authenticates (token mode: 401 without a valid bearer token).
api_router = APIRouter(prefix="/api", dependencies=[Depends(get_actor)])

api_router.include_router(blueprint_router)
api_router.include_router(initiatives_router)
api_router.include_router(test_run_router)
api_router.include_router(registry_router)
