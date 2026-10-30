"""Top-level API routers. Every JSON route is served under `/api`."""

from fastapi import APIRouter, Depends

from app.auth.dependencies import get_actor
from app.azure_devops.routes import public_router as ado_public_router
from app.azure_devops.routes import router as ado_router
from app.blueprint.routes import router as blueprint_router
from app.initiatives.routes import router as initiatives_router
from app.knowledge.routes import router as knowledge_router
from app.people.routes import router as people_router
from app.teams.routes import public_router as teams_public_router
from app.teams.routes import router as teams_router

# Every /api route authenticates (token mode: 401 without a valid bearer token).
api_router = APIRouter(prefix="/api", dependencies=[Depends(get_actor)])

api_router.include_router(blueprint_router)
api_router.include_router(initiatives_router)
api_router.include_router(people_router)
api_router.include_router(teams_router)
api_router.include_router(knowledge_router)
api_router.include_router(ado_router)

# Inbound webhooks authenticate themselves (a platform signature or a shared secret), not
# with our bearer tokens. Each handler verifies before it reads anything.
hooks_router = APIRouter(prefix="/api")
hooks_router.include_router(teams_public_router)
hooks_router.include_router(ado_public_router)
