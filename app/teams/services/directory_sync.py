"""Pull every Teams (Entra ID) user via Microsoft Graph into the people directory."""

from sqlalchemy.orm import Session

from app.exceptions import ValidationException
from app.people.services.people_service import PeopleService, SyncResult
from app.teams.services.clients import GraphClient
from config.settings import settings


def sync_teams_people(db: Session, graph: GraphClient = None) -> SyncResult:
    if not settings.teams.enabled():
        raise ValidationException(message="Teams is not configured (TEAMS_TENANT_ID, TEAMS_GRAPH_CLIENT_ID, TEAMS_GRAPH_CLIENT_SECRET)")
    entries = (graph or GraphClient()).list_users()
    result = PeopleService(db).sync("teams", entries)
    db.commit()
    return result
