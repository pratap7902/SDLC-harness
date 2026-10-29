"""FastAPI dependencies: the authenticated caller. Every /api route depends on `get_actor`
(api_router), so token mode fails closed on reads as well as writes."""

from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.auth.services.authenticator import auth_mode, authenticate
from app.core.database import get_primary_db
from app.core.utils.actor import Actor, require_human, require_role


def get_actor(request: Request, db: Annotated[Session, Depends(get_primary_db)]) -> Actor:
    actor = getattr(request.state, "actor", None)
    if actor is None:
        actor = authenticate(request.headers, db)
        request.state.actor = actor
    return actor


Caller = Annotated[Actor, Depends(get_actor)]


def human(actor: Caller) -> Actor:
    return require_human(actor)


Human = Annotated[Actor, Depends(human)]


def admin(actor: Caller) -> Actor:
    """Service administration: token role `admin`. In local header mode any human is admin
    (X-Actor-Roles: admin also works)."""
    if actor.kind == "human" and auth_mode() == "header":
        return actor
    return require_role(actor, "admin")


Admin = Annotated[Actor, Depends(admin)]
