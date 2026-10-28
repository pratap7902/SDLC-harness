from typing import Annotated

from fastapi import APIRouter, Depends

from app.blueprint.services.blueprint_service import BlueprintService

Service = Annotated[BlueprintService, Depends()]

router = APIRouter(prefix="/blueprint", tags=["blueprint"])


@router.get("")
def get_blueprint(service: Service):
    """Record types, fields (limits, vocabularies, human-only flags, typed links), rules."""
    return service.blueprint()


@router.get("/lifecycle")
def get_lifecycle(service: Service):
    """Phases, derived-status rules, catalogs, gates, routing, SLAs."""
    return service.lifecycle()
