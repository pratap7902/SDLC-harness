"""Azure DevOps Boards REST client (Work Item Tracking, api-version 7.1), PAT auth
(`Authorization: Basic base64(":" + PAT)`). Written against the documented API; tested
with mocked HTTP only.

  GET  {base}/{org}/{project}/_apis/wit/workitems/{id}?$expand=all
  POST {base}/{org}/{project}/_apis/wit/workitems/${type}    (application/json-patch+json)
       — the parent link is a `System.LinkTypes.Hierarchy-Reverse` relation."""

import base64
import html
import re
from typing import Optional
from urllib.parse import quote

from app.core.utils import http
from app.exceptions import NotFoundException, ServerException, ValidationException
from config.settings import settings

WORK_ITEM_URL_RE = re.compile(r"/_workitems/edit/(\d+)|/_apis/wit/workitems/(\d+)", re.I)


def work_item_id(ref) -> int:
    """`1234`, `#1234` or a work item URL → 1234."""
    text = str(ref or "").strip().lstrip("#")
    if text.isdigit():
        return int(text)
    m = WORK_ITEM_URL_RE.search(text)
    if m:
        return int(m.group(1) or m.group(2))
    raise ValidationException(message=f"work_item: give an id or a work item link (…/_workitems/edit/<id>), not {text[:80]!r}")


def html_to_markdown(value: Optional[str]) -> str:
    """ADO rich text is HTML. Enough of it becomes markdown to read as a requirement."""
    text = value or ""
    text = re.sub(r"(?is)<(script|style).*?</\1>", "", text)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)<h([1-6])[^>]*>", lambda m: "\n" + "#" * min(int(m.group(1)) + 1, 6) + " ", text)
    text = re.sub(r"(?i)<li[^>]*>", "\n- ", text)
    text = re.sub(r"(?i)</(p|div|h[1-6]|ul|ol|li|tr)>", "\n", text)
    text = re.sub(r"(?i)<(b|strong)>(.*?)</\1>", r"**\2**", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text).replace("\xa0", " ")
    return re.sub(r"\n{3,}", "\n\n", "\n".join(line.rstrip() for line in text.splitlines())).strip()


class AdoClient:
    def __init__(self):
        self.s = settings.azure_devops

    def _check(self) -> None:
        if not self.s.enabled():
            raise ValidationException(message="Azure DevOps is not configured (ADO_ORG, ADO_PROJECT, ADO_PAT)", error_code="ADO_DISABLED")

    def _headers(self, content_type: str = "application/json") -> dict:
        token = base64.b64encode(f":{self.s.ADO_PAT}".encode()).decode()
        return {"Authorization": f"Basic {token}", "Content-Type": content_type, "Accept": "application/json"}

    def project_url(self) -> str:
        return f"{self.s.ADO_BASE_URL.rstrip('/')}/{quote(self.s.ADO_ORG)}/{quote(self.s.ADO_PROJECT)}"

    def web_url(self, item_id: int) -> str:
        return f"{self.project_url()}/_workitems/edit/{item_id}"

    def get(self, item_id: int) -> dict:
        self._check()
        with http.client() as c:
            r = c.get(f"{self.project_url()}/_apis/wit/workitems/{item_id}", params={"$expand": "all", "api-version": self.s.ADO_API_VERSION}, headers=self._headers())
        if r.status_code == 404:
            raise NotFoundException(message=f"No Azure DevOps work item {item_id}")
        if r.status_code != 200 or "json" not in r.headers.get("content-type", ""):
            # a bad PAT gets a 203 + HTML sign-in page from ADO
            raise ServerException(message=f"Azure DevOps work item {item_id}: {r.status_code} {r.text[:160]}")
        return r.json()

    def create_child(self, parent_id: int, title: str, description_html: str) -> dict:
        self._check()
        patch = [
            {"op": "add", "path": "/fields/System.Title", "value": title[:255]},
            {"op": "add", "path": "/fields/System.Description", "value": description_html},
            {"op": "add", "path": "/relations/-", "value": {"rel": "System.LinkTypes.Hierarchy-Reverse", "url": f"{self.project_url()}/_apis/wit/workItems/{parent_id}"}},
        ]
        with http.client() as c:
            r = c.post(
                f"{self.project_url()}/_apis/wit/workitems/${quote(self.s.ADO_CHILD_TYPE)}",
                params={"api-version": self.s.ADO_API_VERSION},
                json=patch,
                headers=self._headers("application/json-patch+json"),
            )
        if r.status_code not in (200, 201) or "json" not in r.headers.get("content-type", ""):
            raise ServerException(message=f"Azure DevOps create {self.s.ADO_CHILD_TYPE}: {r.status_code} {r.text[:160]}")
        return r.json()
