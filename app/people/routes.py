"""The people directory (`/api/people`, read by the UI's "Viewing as" list and the
assignment pickers) and its administration (`/api/admin/people…`, token role admin)."""

from typing import Annotated, Optional

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.auth.dependencies import Admin
from app.core.database import get_primary_db
from app.initiatives.services.inbox_service import InboxService
from app.people.requests import CreatePersonRequest, ResolvePeopleReviewRequest
from app.people.services.people_service import PeopleService, person_json, review_json

router = APIRouter(tags=["people"])
Db = Annotated[Session, Depends(get_primary_db)]


@router.get("/people")
def people(inbox: Annotated[InboxService, Depends()], db: Db):
    """Everyone: the canonical directory merged with every handle that holds an assignment
    or has something routed to them. `in_directory: false` = a handle no person row has
    yet (create it under /api/admin/people)."""
    directory = PeopleService(db).directory()
    rows = {}
    for row in inbox.people():
        entry = directory.get(row["person"])
        rows[row["person"]] = {**row, **_directory_fields(entry)}
    for handle, entry in directory.items():
        if handle not in rows and entry["active"]:
            rows[handle] = {"person": handle, "roles": [], "inbox": 0, **_directory_fields(entry)}
    return sorted(rows.values(), key=lambda p: p["person"])


def _directory_fields(entry: Optional[dict]) -> dict:
    if entry is None:
        return {"name": None, "email": None, "in_directory": False, "teams_user_id": None, "identities": []}
    teams = next((i["external_id"] for i in entry["identities"] if i["source"] == "teams" and i["active"]), None)
    return {"name": entry["name"], "email": entry["email"], "in_directory": True, "teams_user_id": teams, "identities": entry["identities"]}


@router.post("/admin/people", status_code=201)
def create_person(body: CreatePersonRequest, db: Db, actor: Admin):
    service = PeopleService(db)
    person = service.create(body.handle, body.name or "", body.email)
    db.commit()
    return person_json(person, [])


@router.get("/admin/people/review")
def people_review(db: Db, actor: Admin, status: Optional[str] = "open"):
    return [review_json(r) for r in PeopleService(db).review(status)]


@router.post("/admin/people/review/{item_id}/resolve")
def resolve_people_review(item_id: int, body: ResolvePeopleReviewRequest, db: Db, actor: Admin):
    item = PeopleService(db).resolve_review(item_id, body.action, actor.name, body.handle, body.name)
    db.commit()
    return review_json(item)
