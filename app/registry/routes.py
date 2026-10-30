"""REST for the repo registry (read). Writes: POST /api/global/records with type `repository`."""

from typing import Annotated

from fastapi import APIRouter, Depends

from app.registry.services.registry_service import RegistryService

router = APIRouter(tags=["registry"])

Registry = Annotated[RegistryService, Depends()]


@router.get("/repos")
def list_repos(service: Registry, include_retired: bool = False):
    """Registered repositories: default branch, test command, JUnit path, templates, owners."""
    return service.list(include_retired)


@router.get("/repos/{owner}/{name}")
def get_repo(owner: str, name: str, service: Registry):
    return service.get(f"{owner}/{name}")
