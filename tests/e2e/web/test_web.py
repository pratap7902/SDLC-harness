from app.web import spa


def test_health(client):
    assert client.get("/health").json() == {"status": "healthy"}


def test_pages_say_the_frontend_is_not_built(client, monkeypatch, tmp_path):
    monkeypatch.setattr(spa, "DIST_DIR", tmp_path)
    r = client.get("/i/order-events/drift")
    assert r.status_code == 404 and "not built" in r.json()["detail"]


def test_pages_serve_the_app_and_assets(client, monkeypatch, tmp_path):
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<div id=root></div>")
    (tmp_path / "assets" / "app.js").write_text("1")
    monkeypatch.setattr(spa, "DIST_DIR", tmp_path)
    for path in ("/", "/new", "/inbox/maya", "/i/x", "/i/x/draft", "/i/x/drift", "/i/x/t/T-1", "/i/x/r/D-1", "/i/x/reviews", "/i/x/activity", "/standards", "/learnings", "/blueprint"):
        r = client.get(path)
        assert r.status_code == 200 and "root" in r.text, path
        assert r.headers["cache-control"] == "no-cache"
    assert client.get("/assets/app.js").headers["cache-control"].startswith("public")
    assert client.get("/assets/../index.html").status_code == 404


def test_cors_for_the_vite_dev_server(client):
    r = client.options("/api/initiatives", headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "x-actor,content-type"})
    assert r.status_code == 200 and r.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_blueprint_endpoints(client):
    bp = client.get("/api/blueprint").json()
    gap = next(t for t in bp["types"] if t["key"] == "gap")
    answer = next(f for f in gap["fields"] if f["name"] == "answer")
    assert answer["actor"] == "human" and gap["status_rule"]["rule"] == "gap_status"
    assert bp["pills"]["APPROVED"] == "green"
    lc = client.get("/api/blueprint/lifecycle").json()
    assert list(lc["gates"]) == ["GATE_DRAFT", "GATE_PR", "GATE_VALIDATED"]
    assert lc["routing"]["by_domain"]["product"] == "product"
