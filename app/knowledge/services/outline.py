"""The Outline knowledge base, through its REST API (POST /api/documents.search,
POST /api/documents.info; `Authorization: Bearer <API key>`). Optional Cloudflare Access
service-token headers (`CF-Access-Client-Id` / `CF-Access-Client-Secret`) get the request
past Access in front of the wiki.

Every result carries a citation records can hold in `cites`:
    kb:outline/<document id>[#<heading anchor>]
The anchor is Outline's heading slug; kb_get with one returns just that section.

Why REST and not Outline's /mcp: the two documented calls are all we need, they are stable
and easy to mock; an MCP client would add a session protocol for the same two reads."""

import re
from dataclasses import asdict, dataclass
from typing import List, Optional, Tuple

from app.blueprint.schemas.blueprint import KB_CITATION_RE
from app.core.utils import http
from app.exceptions import NotFoundException, ServerException, ValidationException
from config.settings import settings

SOURCE = "outline"
HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
TAGS = re.compile(r"</?[^>]+>")


@dataclass
class KbHit:
    citation: str
    title: str
    url: str
    snippet: str
    updated_at: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class KbDoc:
    citation: str
    title: str
    url: str
    text: str
    section: Optional[str] = None
    updated_at: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)


def slug(heading: str) -> str:
    """Outline's heading anchor: lower-case, non-alphanumerics → '-'."""
    return re.sub(r"[^a-z0-9]+", "-", heading.lower()).strip("-")


def section(markdown: str, anchor: str) -> Optional[str]:
    """The section under the heading whose slug is `anchor`, up to the next heading of the
    same or a higher level."""
    lines = markdown.splitlines()
    for i, line in enumerate(lines):
        m = HEADING.match(line)
        if m and slug(m.group(2)) == anchor:
            level = len(m.group(1))
            out = [line]
            for nxt in lines[i + 1 :]:
                n = HEADING.match(nxt)
                if n and len(n.group(1)) <= level:
                    break
                out.append(nxt)
            return "\n".join(out).strip()
    return None


def parse_citation(value: str) -> Tuple[str, Optional[str]]:
    """`kb:outline/<id>#a` or a bare id → (id, anchor)."""
    value = (value or "").strip()
    if value.startswith("kb:"):
        m = KB_CITATION_RE.match(value)
        if not m or m.group(1) != SOURCE:
            raise ValidationException(message=f"'{value}' is not an Outline citation (kb:outline/<doc-id>[#anchor])")
        return m.group(2), (m.group(3) or "")[1:] or None
    doc, _, anchor = value.partition("#")
    if not doc:
        raise ValidationException(message="give a citation (kb:outline/<doc-id>) or a document id")
    return doc, anchor or None


class OutlineClient:
    def __init__(self):
        self.s = settings.knowledge

    def _headers(self) -> dict:
        if not self.s.enabled():
            raise ValidationException(message="The knowledge base is not configured (OUTLINE_URL, OUTLINE_API_KEY)", error_code="KB_DISABLED")
        h = {"Authorization": f"Bearer {self.s.OUTLINE_API_KEY}", "Accept": "application/json"}
        if self.s.OUTLINE_CF_ACCESS_CLIENT_ID:
            h["CF-Access-Client-Id"] = self.s.OUTLINE_CF_ACCESS_CLIENT_ID
            h["CF-Access-Client-Secret"] = self.s.OUTLINE_CF_ACCESS_CLIENT_SECRET
        return h

    def _post(self, method: str, body: dict) -> dict:
        headers = self._headers()
        with http.client() as c:
            r = c.post(f"{self.s.OUTLINE_URL.rstrip('/')}/api/{method}", json=body, headers=headers)
        if r.status_code in (400, 404) and method == "documents.info":
            raise NotFoundException(message=f"No Outline document {body.get('id')}")
        if r.status_code != 200 or "json" not in r.headers.get("content-type", ""):
            # a Cloudflare Access login page comes back as HTML with 200/302
            raise ServerException(message=f"Outline {method}: {r.status_code} {r.text[:160]}")
        return r.json()

    def _url(self, path: str) -> str:
        return path if path.startswith("http") else self.s.OUTLINE_URL.rstrip("/") + path

    def search(self, query: str, limit: int = 8) -> List[KbHit]:
        if not (query or "").strip():
            raise ValidationException(message="query: required")
        body = self._post("documents.search", {"query": query.strip(), "limit": max(1, min(limit, 25))})
        out = []
        for row in body.get("data") or []:
            doc = row.get("document") or {}
            if not doc.get("id"):
                continue
            snippet = " ".join(TAGS.sub("", row.get("context") or "").split())
            out.append(KbHit(f"kb:{SOURCE}/{doc['id']}", doc.get("title") or "", self._url(doc.get("url") or ""), snippet[:300], doc.get("updatedAt")))
        return out

    def get(self, citation: str) -> KbDoc:
        doc_id, anchor = parse_citation(citation)
        doc = (self._post("documents.info", {"id": doc_id}).get("data")) or {}
        text = doc.get("text") or ""
        part = None
        if anchor:
            part = section(text, anchor)
            if part is None:
                raise NotFoundException(message=f"No heading #{anchor} in Outline document {doc_id}")
        cite = f"kb:{SOURCE}/{doc.get('id') or doc_id}" + (f"#{anchor}" if anchor else "")
        url = self._url(doc.get("url") or "") + (f"#{anchor}" if anchor else "")
        return KbDoc(cite, doc.get("title") or "", url, part if part is not None else text, anchor, doc.get("updatedAt"))
