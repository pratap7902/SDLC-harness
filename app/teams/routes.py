"""Teams: the bot's messaging endpoint (public — verified by the Bot Framework JWT, not by
our bearer tokens) and the admin operations (directory sync, notification run)."""

from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.auth.dependencies import Admin
from app.core.database import get_primary_db
from app.exceptions import ValidationException
from app.teams.services.directory_sync import sync_teams_people
from app.teams.services.inbound import TeamsInbound
from app.teams.services.notifications import Notifier

router = APIRouter(tags=["teams"])  # under the authenticated /api router
public_router = APIRouter(tags=["teams"])  # under /api, authenticated by its own signature
Db = Annotated[Session, Depends(get_primary_db)]


@public_router.post("/teams/messages")
async def teams_messages(request: Request, db: Db):
    """Bot Framework activities (card button clicks). 401 unless signed by the Bot
    Connector for this bot."""
    try:
        activity = await request.json()
    except ValueError as e:
        raise ValidationException(message="body: a Bot Framework activity (JSON)") from e
    return TeamsInbound(db).handle(request.headers, activity)


@router.post("/admin/people/sync")
def sync_people(db: Db, actor: Admin):
    """Pull Teams users (Microsoft Graph) into the people directory, merged by email."""
    return sync_teams_people(db).to_dict()


@router.post("/admin/notifications/run")
def run_notifications(db: Db, actor: Admin):
    """Send what is due to Teams (idempotent: deliveries are keyed)."""
    return Notifier(db).run()


@router.get("/admin/deliveries")
def deliveries(db: Db, actor: Admin, status: Optional[str] = None, limit: int = 200):
    return Notifier(db).deliveries(status, limit)
