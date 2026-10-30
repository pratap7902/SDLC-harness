"""Azure DevOps Boards: import a work item, prefill the Start feature form, push tasks
(authenticated /api), and the service-hook endpoint (public; verified by the shared
secret)."""

from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.auth.dependencies import Caller
from app.azure_devops.services.boards_service import BoardsService
from app.core.database import get_primary_db
from app.exceptions import ValidationException

router = APIRouter(tags=["azure-devops"])
public_router = APIRouter(tags=["azure-devops"])
Db = Annotated[Session, Depends(get_primary_db)]


class ImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    work_item: str = Field(description="work item id or link")
    dri: Optional[str] = None
    engg: Optional[str] = None
    product: Optional[str] = None
    design: Optional[str] = None
    qa: Optional[str] = None
    slug: Optional[str] = None


@router.get("/azure-devops/preview")
def preview(work_item: str, db: Db):
    """What importing this work item would start: title, requirement, link, the DRI / engg
    matched in the people directory (`unmatched`: emails that are not)."""
    return BoardsService(db).preview(work_item)


@router.post("/azure-devops/import", status_code=201)
def import_work_item(body: ImportRequest, db: Db, actor: Caller):
    """Start a feature from a work item through the intake (IntakeService.start)."""
    return BoardsService(db).import_item(body.work_item, actor, body.model_dump(exclude={"work_item"}))


@router.post("/initiatives/{initiative_id}/azure-devops/push-tasks")
def push_tasks(initiative_id: int, db: Db, actor: Caller):
    """One-way: each task with no tracker_id becomes a child of the feature's work item."""
    return BoardsService(db).push_tasks(initiative_id)


@public_router.post("/hooks/azure-devops")
async def service_hook(request: Request, db: Db):
    """Service hook (Web Hooks) for workitem.updated / workitem.created."""
    BoardsService.verify(request.headers)
    try:
        event = await request.json()
    except ValueError as e:
        raise ValidationException(message="body: a service hook event (JSON)") from e
    return BoardsService(db).handle_event(request.headers, event)
