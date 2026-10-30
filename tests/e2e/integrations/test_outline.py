"""Outline knowledge base against mocked HTTP: search and get, the citation, the
Cloudflare Access service-token headers, citing a result in a record."""

import httpx
import pytest

from app.mcp import server
from config.settings import settings
from tests.fixtures.mock_http import MockHttp, install
from tests.fixtures.slice import SLUG, to_task

BASE = "https://wiki.example.com"
DOC = "3f2a9c1e-7b4d-4e8a-9c0f-1a2b3c4d5e6f"
TEXT = "# Event standards\nIntro.\n\n## Partition keys\nUse the aggregate id.\n\n### Example\norder_id\n\n## Envelopes\nCloudEvents 1.0."


@pytest.fixture
def outline(monkeypatch) -> MockHttp:
    monkeypatch.setattr(settings.knowledge, "OUTLINE_URL", BASE)
    monkeypatch.setattr(settings.knowledge, "OUTLINE_API_KEY", "ol_api_test")
    monkeypatch.setattr(settings.knowledge, "OUTLINE_CF_ACCESS_CLIENT_ID", "cf-id.access")
    monkeypatch.setattr(settings.knowledge, "OUTLINE_CF_ACCESS_CLIENT_SECRET", "cf-secret")
    mock = install(monkeypatch)
    mock.on("POST", rf"{BASE}/api/documents\.search$", {"data": [{"ranking": 0.9, "context": "Use the <b>aggregate</b> id", "document": {"id": DOC, "title": "Event standards", "url": "/doc/event-standards-AbC123", "updatedAt": "2026-10-01T00:00:00Z"}}]})
    mock.on("POST", rf"{BASE}/api/documents\.info$", lambda r: {"data": {"id": DOC, "title": "Event standards", "text": TEXT, "url": "/doc/event-standards-AbC123"}} if MockHttp.body(r)["id"] == DOC else httpx.Response(404, json={"ok": False}))
    return mock


def test_kb_search_returns_citations_and_sends_the_access_headers(outline):
    out = server.kb_search("partition key")
    assert out.splitlines()[0] == f"kb:outline/{DOC} — Event standards"
    assert "Use the aggregate id" in out  # tags stripped
    (req,) = outline.sent("POST", r"documents\.search")
    assert req.headers["authorization"] == "Bearer ol_api_test"
    assert req.headers["cf-access-client-id"] == "cf-id.access" and req.headers["cf-access-client-secret"] == "cf-secret"
    assert MockHttp.body(req) == {"query": "partition key", "limit": 8}


def test_kb_get_whole_and_by_section(outline):
    whole = server.kb_get(f"kb:outline/{DOC}")
    assert whole.startswith(f"kb:outline/{DOC} — Event standards\n{BASE}/doc/event-standards-AbC123") and "Envelopes" in whole
    part = server.kb_get(f"kb:outline/{DOC}#partition-keys")
    assert "Use the aggregate id" in part and "order_id" in part and "CloudEvents" not in part
    with pytest.raises(ValueError, match="No heading"):
        server.kb_get(f"kb:outline/{DOC}#nope")
    with pytest.raises(ValueError, match="No Outline document"):
        server.kb_get("kb:outline/missing-doc")
    with pytest.raises(ValueError, match="not an Outline citation"):
        server.kb_get("kb:confluence/123")


def test_an_access_login_page_is_an_error_not_an_empty_result(outline):
    outline.on("POST", r"documents\.search", httpx.Response(200, text="<html>Sign in</html>", headers={"content-type": "text/html"}))
    with pytest.raises(ValueError, match="Outline documents.search"):
        server.kb_search("x")


def test_kb_off_when_not_configured(monkeypatch):
    monkeypatch.setattr(settings.knowledge, "OUTLINE_API_KEY", "")
    with pytest.raises(ValueError, match="not configured"):
        server.kb_search("x")


def test_records_cite_kb_citations(api, outline):
    to_task(api)
    out = api.write(SLUG, [{"type": "finding", "fields": {"summary": "partition key per standard", "severity": "nit", "target": ["T-1"], "cites": [f"kb:outline/{DOC}#partition-keys"]}}])
    assert out["ok"]
    errors = api.rejected(SLUG, [{"type": "finding", "fields": {"summary": "x", "severity": "nit", "target": ["T-1"], "cites": ["kb:outline/bad id"]}}])
    assert errors[0].startswith("cites[0]: 'kb:outline/bad id' is not a citation")
    assert api.ok(api.as_("priya").get("/api/kb/search", params={"q": "partition"}))[0]["citation"] == f"kb:outline/{DOC}"
