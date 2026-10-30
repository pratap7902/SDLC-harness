"""Microsoft Teams against mocked Graph / Bot Connector HTTP (no network): the directory
sync and its merge rules, notifications with idempotent deliveries, and inbound card
actions going through the human-only paths."""

import time

import httpx
import pytest

from app.people.services.people_service import PeopleService
from app.teams.services import clients, inbound
from config.settings import settings
from tests.fixtures.mock_http import MockHttp, install
from tests.fixtures.rsa import jwk, sign
from tests.fixtures.slice import SLUG, deviation_gap, to_task

TENANT, BOT = "tenant-1", "bot-app-1"
SERVICE = "https://smba.example/teams/"


@pytest.fixture
def teams(monkeypatch, db_session) -> MockHttp:
    for k, v in {
        "TEAMS_TENANT_ID": TENANT, "TEAMS_GRAPH_CLIENT_ID": "graph-app", "TEAMS_GRAPH_CLIENT_SECRET": "s3cret",
        "TEAMS_BOT_APP_ID": BOT, "TEAMS_BOT_APP_SECRET": "b0t", "TEAMS_SERVICE_URL": SERVICE,
    }.items():
        monkeypatch.setattr(settings.teams, k, v)
    monkeypatch.setattr(clients.GraphClient, "_token", clients._Token())
    monkeypatch.setattr(clients.BotClient, "_token", clients._Token())
    monkeypatch.setattr(inbound, "_jwks", {})
    mock = install(monkeypatch)
    mock.on("POST", r"login\.microsoftonline\.com/tenant-1/oauth2/v2\.0/token", {"access_token": "tok", "expires_in": 3600})
    mock.on("GET", r"login\.botframework\.com/v1/\.well-known/keys", {"keys": [jwk("bf1")]})
    return mock


def graph_users(mock: MockHttp, *pages):
    """Graph /users, paged with @odata.nextLink."""
    for i, page in enumerate(pages):
        nxt = {"@odata.nextLink": f"https://graph.microsoft.com/v1.0/users?page={i + 1}"} if i + 1 < len(pages) else {}
        pattern = r"graph\.microsoft\.com/v1\.0/users\?\$select" if i == 0 else rf"graph\.microsoft\.com/v1\.0/users\?page={i}$"
        mock.on("GET", pattern, {"value": page, **nxt})


def user(oid, name, mail, enabled=True, upn=None):
    return {"id": oid, "displayName": name, "mail": mail, "userPrincipalName": upn or mail or f"{oid}@acme.onmicrosoft.com", "accountEnabled": enabled}


def directory(db, *people):
    service = PeopleService(db)
    for handle, email in people:
        service.create(handle, handle.title(), email)
    db.commit()


# ── directory sync ─────────────────────────────────────────────────────────────


def test_sync_merges_by_email_and_sends_the_rest_to_review(api, db_session, teams):
    directory(db_session, ("priya", "Priya@Acme.dev"), ("maya", "maya@acme.dev"))
    graph_users(
        teams,
        [user("oid-priya", "Priya R", "priya@acme.dev"), user("oid-x", "Xavier", "xavier@acme.dev")],
        [user("oid-b1", "Bob", "bob@acme.dev"), user("oid-b2", "Bob (admin)", "bob@acme.dev"), user("oid-n", "No Mail", None, upn="n#EXT#@acme.onmicrosoft.com")],
    )
    out = api.ok(api.as_("chandra").post("/api/admin/people/sync"))
    assert out["seen"] == 5 and out["linked"] == ["priya"]
    assert sorted(out["unmatched"]) == ["oid-n", "oid-x"] and sorted(out["conflicts"]) == ["oid-b1", "oid-b2"]
    # Graph token request is client credentials for Graph
    assert b"scope=https%3A%2F%2Fgraph.microsoft.com%2F.default" in teams.sent("POST", r"oauth2")[0].content
    review = api.ok(api.as_("chandra").get("/api/admin/people/review"))
    assert sorted((r["external_id"], r["reason"]) for r in review) == [("oid-b1", "conflict"), ("oid-b2", "conflict"), ("oid-n", "unmatched"), ("oid-x", "unmatched")]
    # a second sync duplicates nothing
    api.ok(api.as_("chandra").post("/api/admin/people/sync"))
    assert len(api.ok(api.as_("chandra").get("/api/admin/people/review"))) == 4
    # the admin creates a person from an unmatched entry — one person, now linked
    x = next(r for r in review if r["external_id"] == "oid-x")
    api.ok(api.as_("chandra").post(f"/api/admin/people/review/{x['id']}/resolve", json={"action": "create", "handle": "xavier"}))
    people = {p["person"]: p for p in api.get("/api/people")}
    assert people["priya"]["teams_user_id"] == "oid-priya" and people["priya"]["email"] == "priya@acme.dev"
    assert people["xavier"]["teams_user_id"] == "oid-x" and people["xavier"]["in_directory"] is True


def test_a_second_account_for_a_linked_person_is_a_conflict_not_a_relink(api, db_session, teams):
    directory(db_session, ("priya", "priya@acme.dev"))
    graph_users(teams, [user("oid-priya", "Priya", "priya@acme.dev")])
    api.ok(api.as_("chandra").post("/api/admin/people/sync"))
    teams.routes.clear()
    teams.on("POST", r"oauth2", {"access_token": "tok", "expires_in": 3600})
    graph_users(teams, [user("oid-priya", "Priya", "priya@acme.dev"), user("oid-priya-2", "Priya (test)", "PRIYA@acme.dev")])
    out = api.ok(api.as_("chandra").post("/api/admin/people/sync"))
    assert out["conflicts"] == ["oid-priya-2"] and out["linked"] == []
    assert PeopleService(db_session).by_identity("teams", "oid-priya").handle == "priya"
    assert PeopleService(db_session).by_identity("teams", "oid-priya-2") is None


def test_admin_endpoints_need_the_admin_role_in_token_mode(api, db_session, monkeypatch):
    from app.auth.services.token_service import TokenService

    plain, _ = TokenService(db_session).mint("runner-sdk", "agent")
    admin, _ = TokenService(db_session).mint("ops", "agent", roles=["admin"])
    monkeypatch.setattr(settings.auth, "AUTH_MODE", "token")
    from fastapi.testclient import TestClient

    from main import app

    assert TestClient(app, headers={"Authorization": f"Bearer {plain}"}).get("/api/admin/people/review").status_code == 403
    assert TestClient(app, headers={"Authorization": f"Bearer {admin}"}).get("/api/admin/people/review").status_code == 200


# ── notifications ──────────────────────────────────────────────────────────────


def _routed_gap(api, db_session):
    """G-2 (deviation, domain engg) routes to priya; priya is on Teams."""
    to_task(api)
    api.write(SLUG, [deviation_gap()])
    directory(db_session, ("priya", "priya@acme.dev"))
    from app.people.models.person import PersonIdentity

    person = PeopleService(db_session).repo.by_handle("priya")
    db_session.add(PersonIdentity(person_id=person.id, source="teams", external_id="oid-priya", email="priya@acme.dev", display_name="Priya", active=True, meta={}))
    db_session.commit()


def bot_ok(mock: MockHttp):
    mock.on("POST", r"smba\.example/teams/v3/conversations$", {"id": "a:conv-priya"})
    mock.on("POST", r"v3/conversations/a:conv-priya/activities$", lambda r: {"id": f"act-{len(mock.calls)}"})


def test_a_routed_gap_is_sent_once_with_option_buttons(api, db_session, teams):
    from app.teams.services.notifications import Notifier

    _routed_gap(api, db_session)
    bot_ok(teams)
    out = Notifier(db_session).run()
    assert out["sent"] >= 1 and not out["failed"]
    (created,) = teams.sent("POST", r"v3/conversations$")
    assert MockHttp.body(created)["members"] == [{"id": "oid-priya"}] and MockHttp.body(created)["tenantId"] == TENANT
    cards = [MockHttp.body(r)["attachments"][0]["content"] for r in teams.sent("POST", r"/activities$")]
    gap = next(c for c in cards if "G-2" in c["body"][0]["text"])
    submits = [a for a in gap["actions"] if a["type"] == "Action.Submit"]
    assert [a["data"]["srs"]["choice"] for a in submits] == ["cdc", "outbox"]
    assert gap["actions"][-1]["type"] == "Action.OpenUrl"
    # idempotent: the next run sends nothing new; the conversation is reused
    sent = len(teams.sent("POST", r"/activities$"))
    again = Notifier(db_session).run()
    assert again["sent"] == 0 and len(teams.sent("POST", r"/activities$")) == sent
    rows = api.ok(api.as_("chandra").get("/api/admin/deliveries"))
    assert any(r["dedupe_key"].startswith(f"gap_routed:{api.id(SLUG)}:G-2:priya") and r["status"] == "sent" for r in rows)


def test_a_failed_send_retries_with_backoff(api, db_session, teams):
    from datetime import timedelta

    from app.core.utils.time import utcnow
    from app.teams.services.notifications import Notifier

    _routed_gap(api, db_session)
    teams.on("POST", r"v3/conversations$", {"id": "a:conv-priya"})
    teams.on("POST", r"/activities$", httpx.Response(503, text="busy"))
    out = Notifier(db_session).run()
    assert out["failed"] >= 1 and out["sent"] == 0
    row = next(r for r in Notifier(db_session).deliveries() if r["kind"] == "gap_routed")
    assert row["status"] == "failed" and row["attempts"] == 1 and "503" in row["last_error"]
    assert Notifier(db_session).run()["waiting"] >= 1  # not before next_attempt_at
    bot_ok(teams)
    later = Notifier(db_session).run(now=utcnow() + timedelta(minutes=5))
    assert later["sent"] >= 1
    row = next(r for r in Notifier(db_session).deliveries() if r["kind"] == "gap_routed")
    assert row["status"] == "sent" and row["attempts"] == 2


# ── inbound card actions ───────────────────────────────────────────────────────


def activity(value, aad="oid-priya", reply_to="act-9"):
    return {
        "type": "message", "id": "in-1", "serviceUrl": SERVICE, "replyToId": reply_to,
        "from": {"id": "29:x", "aadObjectId": aad}, "conversation": {"id": "a:conv-priya"}, "value": {"srs": value},
    }


def bot_token(**over):
    claims = {"iss": "https://api.botframework.com", "aud": BOT, "serviceurl": SERVICE, "exp": time.time() + 300, **over}
    return {"Authorization": f"Bearer {sign(claims, kid='bf1')}"}


def post(api, body, headers):
    from fastapi.testclient import TestClient

    from main import app

    return TestClient(app, headers=headers).post("/api/teams/messages", json=body)


def test_answering_a_gap_from_teams_goes_through_the_human_path(api, db_session, teams):
    _routed_gap(api, db_session)
    teams.on("PUT", r"v3/conversations/a:conv-priya/activities/act-9$", {"id": "act-9"})
    iid = api.id(SLUG)
    r = post(api, activity({"action": "answer_gap", "initiative_id": iid, "ref": "G-2", "choice": "cdc"}), bot_token())
    assert r.status_code == 200 and r.json()["handled"] is True
    g2 = api.record(SLUG, "G-2")
    assert g2["status"] == "ANSWERED"
    assert (g2["fields"]["answered_by"], g2["fields"]["answered_via"], g2["fields"]["choice"]) == ("priya", "teams", "cdc")
    assert g2["stamps"]["answer"]["kind"] == "human"
    (update,) = teams.sent("PUT", r"/activities/act-9$")
    assert "answered" in MockHttp.body(update)["attachments"][0]["content"]["body"][1]["text"]
    # the web path records web
    api.write(SLUG, [{"type": "gap", "fields": {"question": "q?", "kind": "unknown", "domain": "engg", "asked_by": "a", "why_now": "w", "context": "c"}}])
    api.answer(SLUG, "G-3", answer="yes", person="priya")
    assert api.record(SLUG, "G-3")["fields"]["answered_via"] == "web"


def test_unsigned_forged_or_unknown_callers_change_nothing(api, db_session, teams):
    _routed_gap(api, db_session)
    teams.on("POST", r"/activities$", {"id": "x"})
    iid = api.id(SLUG)
    act = activity({"action": "answer_gap", "initiative_id": iid, "ref": "G-2", "choice": "cdc"})
    assert post(api, act, {}).status_code == 401
    assert post(api, act, {"Authorization": f"Bearer {sign({'iss': 'https://api.botframework.com', 'aud': BOT}, kid='bf1', seed=9)}"}).status_code == 401
    assert post(api, act, bot_token(aud="someone-else")).status_code == 401
    assert post(api, act, bot_token(serviceurl="https://evil.example/")).status_code == 401
    r = post(api, activity({"action": "answer_gap", "initiative_id": iid, "ref": "G-2", "choice": "cdc"}, aad="oid-stranger"), bot_token())
    assert r.status_code == 200 and r.json()["handled"] is False
    assert api.record(SLUG, "G-2")["status"] == "OPEN"


def test_upholding_a_review_item_from_teams(api, db_session, teams):
    _routed_gap(api, db_session)
    api.answer(SLUG, "G-2", choice="cdc", person="priya")
    items = [i for i in api.get(f"{api.base(SLUG)}/reviews") if i["route_to"] == "priya"]
    assert items
    teams.on("PUT", r"/activities/act-9$", {"id": "act-9"})
    r = post(api, activity({"action": "uphold_review", "initiative_id": api.id(SLUG), "review_item_id": items[0]["id"]}), bot_token())
    assert r.json()["handled"] is True
    done = [i for i in api.get(f"{api.base(SLUG)}/reviews", status="upheld") if i["id"] == items[0]["id"]]
    assert done and done[0]["resolved_by"] == "priya"
