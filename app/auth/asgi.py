"""An ASGI guard for apps mounted outside FastAPI's dependency system (the MCP app): the
same `authenticate` as /api, so token mode answers 401 before any tool runs."""

import json

from app.auth.services.authenticator import authenticate
from app.core import database
from app.exceptions import BaseAppException


class AuthGuard:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers") or []}
        headers.pop("x-actor-kind", None)  # MCP callers are agents whatever they claim
        try:
            authenticate(headers, db_factory=database.SessionLocalPrimary)
        except BaseAppException as e:
            body = json.dumps({"title": e.message, "status": e.status_code, "error_code": e.error_code}).encode()
            await send({"type": "http.response.start", "status": e.status_code, "headers": [(b"content-type", b"application/problem+json"), (b"www-authenticate", b"Bearer")]})
            await send({"type": "http.response.body", "body": body})
            return
        return await self.app(scope, receive, send)
