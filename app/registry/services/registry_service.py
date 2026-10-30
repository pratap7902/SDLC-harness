"""The repo registry: `repository` records in the global scope (blueprint/objects.yaml), so a
repo's default branch, test command, JUnit path, paved-road templates and owners go through
the same write path, revisions and review queue as everything else. Humans set
`test_command` (it is executed by the runner); everything else may be written by anyone.

Reads only here — writes are `POST /api/global/records` like standards and learnings."""

from typing import Annotated, List, Optional

from fastapi import Depends

from app.exceptions import NotFoundException
from app.initiatives.services.record_service import GLOBAL_SLUG, RecordService
from app.initiatives.services.views import record_json


def repo_json(r, g) -> dict:
    """One shape for REST, MCP and the runner."""
    f = r.fields or {}
    name = f.get("name") or ""
    return {
        "ref": r.ref,
        "name": name,
        "status": r.status,
        "default_branch": f.get("default_branch") or "main",
        "local_path": f.get("local_path") or "",
        "clone_url": f.get("clone_url") or (f"https://github.com/{name}.git" if name and "/" in name else ""),
        "test_command": f.get("test_command") or "",
        "junit_path": f.get("junit_path") or "",
        "templates": list(f.get("templates") or []),
        "owners": list(f.get("owners") or []),
        "notes": f.get("notes") or "",
        "record": record_json(r, g),
    }


class RegistryService:
    def __init__(self, records: Annotated[RecordService, Depends()]):
        self.records = records

    def _graph(self):
        return self.records.graph(self.records.initiative(GLOBAL_SLUG))

    def list(self, include_retired: bool = False) -> List[dict]:
        g = self._graph()
        return [repo_json(r, g) for r in g.of_type("repository") if include_retired or r.status != "RETIRED"]

    def find(self, name: str) -> Optional[dict]:
        wanted = (name or "").strip().lower().removesuffix(".git")
        g = self._graph()
        hits = [r for r in g.of_type("repository") if str((r.fields or {}).get("name") or "").lower() == wanted]
        live = [r for r in hits if r.status != "RETIRED"] or hits
        return repo_json(live[-1], g) if live else None

    def get(self, name: str) -> dict:
        repo = self.find(name)
        if repo is None:
            raise NotFoundException(
                message=f"No repository '{name}' in the registry — a human adds it (POST /api/global/records, type repository)",
                error_code="REPO_NOT_REGISTERED",
            )
        return repo


__all__ = ["RegistryService", "repo_json", "GLOBAL_SLUG"]
