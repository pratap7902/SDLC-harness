"""HTTP clients for Microsoft Teams, written against the documented APIs (mock-tested only;
see docs/integrations.md for what is unverified against a live tenant).

GraphClient — app-only (client credentials) Microsoft Graph:
  POST {login}/{tenant}/oauth2/v2.0/token  scope=https://graph.microsoft.com/.default
  GET  /users?$select=id,displayName,mail,userPrincipalName,accountEnabled&$top=999
       (follows @odata.nextLink) · GET /users/{id}
  Permission: User.Read.All (application), admin consent.

BotClient — Bot Framework Connector (the Teams channel), single-tenant bot:
  POST {login}/{tenant}/oauth2/v2.0/token  scope=https://api.botframework.com/.default
  POST {serviceUrl}v3/conversations                       — 1:1 chat with a user (proactive)
  POST {serviceUrl}v3/conversations/{id}/activities       — send
  PUT  {serviceUrl}v3/conversations/{id}/activities/{aid} — update (replace a card)
  The bot must be installed for the user (Teams admin policy, or Graph
  POST /users/{id}/teamwork/installedApps) before a proactive 1:1 chat can be created."""

import time
from dataclasses import dataclass
from typing import Dict, List, Optional

from app.core.utils import http
from app.people.services.people_service import DirectoryEntry
from config.settings import settings

GRAPH_SELECT = "id,displayName,mail,userPrincipalName,accountEnabled"


class TeamsError(Exception):
    pass


@dataclass
class _Token:
    value: str = ""
    expires: float = 0.0


def _client_credentials(tenant: str, client_id: str, secret: str, scope: str, cache: _Token) -> str:
    if cache.value and cache.expires - 60 > time.time():
        return cache.value
    with http.client() as c:
        r = c.post(
            f"{settings.teams.TEAMS_LOGIN_URL}/{tenant}/oauth2/v2.0/token",
            data={"grant_type": "client_credentials", "client_id": client_id, "client_secret": secret, "scope": scope},
        )
    if r.status_code != 200:
        raise TeamsError(f"token request failed: {r.status_code} {r.text[:200]}")
    body = r.json()
    cache.value, cache.expires = body["access_token"], time.time() + int(body.get("expires_in", 3600))
    return cache.value


def to_entry(user: dict) -> DirectoryEntry:
    """A Graph user → a directory entry. `mail` is the address; guests and some accounts
    have none, so the UPN stands in when it looks like an address."""
    email = user.get("mail") or (user.get("userPrincipalName") if "@" in (user.get("userPrincipalName") or "") and "#EXT#" not in (user.get("userPrincipalName") or "") else None)
    return DirectoryEntry(
        external_id=user["id"],
        display_name=user.get("displayName") or "",
        email=email,
        active=bool(user.get("accountEnabled", True)),
    )


class GraphClient:
    _token = _Token()

    def __init__(self):
        self.s = settings.teams

    def _headers(self) -> Dict[str, str]:
        token = _client_credentials(self.s.TEAMS_TENANT_ID, self.s.TEAMS_GRAPH_CLIENT_ID, self.s.TEAMS_GRAPH_CLIENT_SECRET, "https://graph.microsoft.com/.default", GraphClient._token)
        return {"Authorization": f"Bearer {token}"}

    def list_users(self) -> List[DirectoryEntry]:
        url: Optional[str] = f"{self.s.TEAMS_GRAPH_URL}/users?$select={GRAPH_SELECT}&$top=999"
        out: List[DirectoryEntry] = []
        with http.client() as c:
            while url:
                r = c.get(url, headers=self._headers())
                if r.status_code != 200:
                    raise TeamsError(f"Graph /users: {r.status_code} {r.text[:200]}")
                body = r.json()
                out += [to_entry(u) for u in body.get("value") or []]
                url = body.get("@odata.nextLink")
        return out

    def get_user(self, user_id: str) -> Optional[DirectoryEntry]:
        with http.client() as c:
            r = c.get(f"{self.s.TEAMS_GRAPH_URL}/users/{user_id}?$select={GRAPH_SELECT}", headers=self._headers())
        if r.status_code == 404:
            return None
        if r.status_code != 200:
            raise TeamsError(f"Graph /users/{user_id}: {r.status_code} {r.text[:200]}")
        return to_entry(r.json())


class BotClient:
    _token = _Token()

    def __init__(self, service_url: Optional[str] = None):
        self.s = settings.teams
        self.service_url = (service_url or self.s.TEAMS_SERVICE_URL).rstrip("/") + "/"

    def _headers(self) -> Dict[str, str]:
        token = _client_credentials(self.s.TEAMS_TENANT_ID, self.s.TEAMS_BOT_APP_ID, self.s.TEAMS_BOT_APP_SECRET, "https://api.botframework.com/.default", BotClient._token)
        return {"Authorization": f"Bearer {token}"}

    def create_conversation(self, aad_object_id: str) -> str:
        body = {
            "isGroup": False,
            "bot": {"id": f"28:{self.s.TEAMS_BOT_APP_ID}"},
            "members": [{"id": aad_object_id}],
            "tenantId": self.s.TEAMS_TENANT_ID,
            "channelData": {"tenant": {"id": self.s.TEAMS_TENANT_ID}},
        }
        with http.client() as c:
            r = c.post(f"{self.service_url}v3/conversations", json=body, headers=self._headers())
        if r.status_code not in (200, 201):
            raise TeamsError(f"create conversation: {r.status_code} {r.text[:200]}")
        return r.json()["id"]

    def send(self, conversation_id: str, activity: dict) -> str:
        with http.client() as c:
            r = c.post(f"{self.service_url}v3/conversations/{conversation_id}/activities", json=activity, headers=self._headers())
        if r.status_code not in (200, 201):
            raise TeamsError(f"send: {r.status_code} {r.text[:200]}")
        return (r.json() or {}).get("id", "")

    def update(self, conversation_id: str, activity_id: str, activity: dict) -> None:
        with http.client() as c:
            r = c.put(f"{self.service_url}v3/conversations/{conversation_id}/activities/{activity_id}", json={**activity, "id": activity_id}, headers=self._headers())
        if r.status_code not in (200, 201):
            raise TeamsError(f"update: {r.status_code} {r.text[:200]}")
