"""Azure DevOps Boards against mocked HTTP: import through the intake, the service hook
raising a prd_drift gap, one-way task push with tracker_edited."""

import base64

import httpx
import pytest
from fastapi.testclient import TestClient

from app.mcp import server
from app.people.services.people_service import PeopleService
from config.settings import settings
from main import app
from tests.fixtures.mock_http import MockHttp, install
from tests.fixtures.slice import draft_batch, task_op

BASE = "https://ado.example.com"
PROJECT = rf"{BASE}/acme-org/Orders"
SECRET = "hook-s3cret"


def item(item_id=4211, rev=3, assigned="priya@acme.dev", **fields):
    return {
        "id": item_id,
        "rev": rev,
        "fields": {
            "System.WorkItemType": "Feature",
            "System.Title": "Order events outbox",
            "System.Description": "<div><p>Emit an event for every order state change.</p><ul><li>no polling</li></ul></div>",
            "Microsoft.VSTS.Common.AcceptanceCriteria": "<p>Downstream gets <b>every</b> change within 5s</p>",
            "System.AssignedTo": {"displayName": "Priya", "uniqueName": assigned},
            "Custom.Engineer": {"displayName": "Arjun", "uniqueName": "arjun@acme.dev"},
            **fields,
        },
        "_links": {"html": {"href": f"{BASE}/acme-org/Orders/_workitems/edit/{item_id}"}},
    }


@pytest.fixture
def ado(monkeypatch, db_session) -> MockHttp:
    for k, v in {"ADO_BASE_URL": BASE, "ADO_ORG": "acme-org", "ADO_PROJECT": "Orders", "ADO_PAT": "pat-123", "ADO_WEBHOOK_SECRET": SECRET, "ADO_ENGG_FIELD": "Custom.Engineer"}.items():
        monkeypatch.setattr(settings.azure_devops, k, v)
    service = PeopleService(db_session)
    for handle in ("priya", "arjun"):
        service.create(handle, handle.title(), f"{handle}@acme.dev")
    db_session.commit()
    mock = install(monkeypatch)
    mock.on("GET", rf"{PROJECT}/_apis/wit/workitems/4211\?", item())
    mock.on("GET", rf"{PROJECT}/_apis/wit/workitems/999\?", httpx.Response(404, json={"message": "not found"}))
    return mock


def test_preview_maps_the_work_item_and_people(api, ado):
    p = api.ok(api.as_("chandra").get("/api/azure-devops/preview", params={"work_item": f"{BASE}/acme-org/Orders/_workitems/edit/4211"}))
    assert p["title"] == "Order events outbox" and p["people"] == {"dri": "priya", "engg": "arjun"}
    assert "Emit an event for every order state change." in p["requirement"] and "- no polling" in p["requirement"]
    assert "## Acceptance criteria" in p["requirement"] and "**every**" in p["requirement"]
    (req,) = ado.sent("GET", r"workitems/4211")
    assert req.headers["authorization"] == "Basic " + base64.b64encode(b":pat-123").decode()
    assert "api-version=7.1" in str(req.url)


def test_import_starts_a_feature_through_the_intake(api, ado):
    out = api.ok(api.as_("chandra").post("/api/azure-devops/import", json={"work_item": "4211", "qa": "sam"}), 201)
    assert out["initiative"]["work_item_url"].endswith("/_workitems/edit/4211")
    iid = out["initiative"]["id"]
    roles = {a["fields"]["role"]: a["fields"]["person"] for a in api.get(f"/api/initiatives/{iid}/records", type="assignment")}
    assert roles == {"dri": "priya", "engg": "arjun", "qa": "sam"}
    snapshot = api.get(f"/api/initiatives/{iid}/records/initiative")["fields"]
    assert snapshot["work_item_url"].endswith("/_workitems/edit/4211")
    # importing it again is refused
    r = api.as_("chandra").post("/api/azure-devops/import", json={"work_item": "4211"})
    assert r.status_code == 409 and r.json()["error_code"] == "ALREADY_IMPORTED"
    assert api.as_("chandra").get("/api/azure-devops/preview", params={"work_item": "999"}).status_code == 404


def test_import_needs_people_it_cannot_match(api, ado):
    ado.on("GET", rf"{PROJECT}/_apis/wit/workitems/4211\?", item(assigned="stranger@acme.dev"))
    r = api.as_("chandra").post("/api/azure-devops/import", json={"work_item": "4211"})
    assert r.status_code == 422 and "stranger@acme.dev is not in the people directory" in r.json()["detail"]
    assert api.ok(api.as_("chandra").post("/api/azure-devops/import", json={"work_item": "4211", "dri": "priya"}), 201)


def test_mcp_import(api, ado):
    ctx = type("C", (), {"request_context": type("R", (), {"request": type("Q", (), {"headers": {"x-actor": "runner-sdk"}})()})()})()
    assert "order-events-outbox" in server.import_work_item("4211", ctx)


def hook(body, **headers):
    return TestClient(app, headers=headers).post("/api/hooks/azure-devops", json=body)


def updated(item_id, fields, rev=4):
    return {"eventType": "workitem.updated", "resource": {"workItemId": item_id, "rev": rev, "fields": fields, "revisedBy": {"displayName": "Maya"}, "revision": {"rev": rev}}}


def _imported(api):
    out = api.ok(api.as_("chandra").post("/api/azure-devops/import", json={"work_item": "4211"}), 201)
    return out["initiative"]["id"]


def test_a_description_edit_raises_one_prd_drift_gap_and_repins_nothing(api, ado):
    iid = _imported(api)
    before = api.get(f"/api/initiatives/{iid}")["initiative"]
    change = updated(4211, {"System.Description": {"oldValue": "<p>old</p>", "newValue": "<p>Also emit refunds.</p>"}})
    assert hook(change).status_code == 401
    assert hook(change, **{"X-SRS-Hook-Secret": "wrong"}).status_code == 401
    out = hook(change, **{"X-SRS-Hook-Secret": SECRET})
    assert out.status_code == 200 and out.json()["handled"][0]["gap"] == "G-1"
    gap = api.get(f"/api/initiatives/{iid}/records/G-1")
    assert gap["fields"]["kind"] == "prd_drift" and gap["status"] == "OPEN" and "Also emit refunds." in gap["fields"]["context"]
    assert api.get(f"/api/initiatives/{iid}")["initiative"]["snapshot_hash"] == before["snapshot_hash"]
    # basic auth works too; a second edit does not pile up a second open gap
    basic = "Basic " + base64.b64encode(f"ado:{SECRET}".encode()).decode()
    assert hook(updated(4211, {"System.Description": {"newValue": "<p>v3</p>"}}, rev=5), Authorization=basic).json()["handled"] == []
    assert len(api.get(f"/api/initiatives/{iid}/records", type="gap")) == 1
    # an edit to a field that is not the requirement raises nothing
    assert hook(updated(4211, {"System.State": {"newValue": "Active"}}), **{"X-SRS-Hook-Secret": SECRET}).json()["handled"] == []


def test_push_tasks_once_and_flag_edits_made_in_ado(api, ado):
    iid = _imported(api)
    base = f"/api/initiatives/{iid}"
    agent = api.agent()
    agent.post(f"{base}/records", json={"ops": draft_batch()[:6]})
    t = task_op()
    t["fields"].update(implements=["D-1"], covers=["AC-1"])
    assert agent.post(f"{base}/records", json={"ops": [t]}).status_code == 200
    created = []

    def create(request):
        patch = MockHttp.body(request)
        created.append(patch)
        return httpx.Response(200, json={"id": 5001, "_links": {"html": {"href": f"{BASE}/acme-org/Orders/_workitems/edit/5001"}}})

    ado.on("POST", rf"{PROJECT}/_apis/wit/workitems/\$Task\?", create)
    # the agent holding T-1's lease does not stop the service storing the tracker id
    api.ok(agent.post("/api/leases/claim", json={"item_key": f"task:{iid}:T-1"}))
    out = api.ok(api.as_("chandra").post(f"{base}/azure-devops/push-tasks"))
    assert out["pushed"] == [{"task": "T-1", "work_item_id": 5001, "url": f"{BASE}/acme-org/Orders/_workitems/edit/5001"}]
    (req,) = ado.sent("POST", r"\$Task")
    assert req.headers["content-type"] == "application/json-patch+json"
    rel = next(op for op in created[0] if op["path"] == "/relations/-")["value"]
    assert rel["rel"] == "System.LinkTypes.Hierarchy-Reverse" and rel["url"].endswith("/workItems/4211")
    t1 = api.get(f"{base}/records/T-1")
    assert t1["fields"]["tracker_id"] == "5001" and t1["stamps"]["tracker_id"]["kind"] == "system"
    assert api.ok(api.as_("chandra").post(f"{base}/azure-devops/push-tasks"))["skipped"] == ["T-1"]
    # someone edits the child in ADO: flagged, never overwritten
    out = hook(updated(5001, {"System.Title": {"oldValue": "T-1: Outbox", "newValue": "Outbox (renamed)"}}), **{"X-SRS-Hook-Secret": SECRET})
    assert out.json()["handled"] == [{"initiative_id": iid, "task": "T-1", "tracker_edited": "yes"}]
    t1 = api.get(f"{base}/records/T-1")
    assert t1["fields"]["tracker_edited"] == "yes" and t1["title"] == "Outbox table and relay"
    work = api.get(f"{base}/worklist")
    assert any(x["kind"] == "tracker" and x["ref"] == "T-1" and x["person"] == "arjun" for x in work["items"])
