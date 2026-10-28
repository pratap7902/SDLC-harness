from app.initiatives.services.routing import Router
from tests.fixtures.graphs import graph, people, rec


def test_domain_routes_to_the_role_assignee():
    g = graph([rec("G-1", domain="product"), rec("D-1", domain="engg")] + people(dri="chandra", engg="priya", product="maya"))
    r = Router(g)
    assert r.route(g.get("G-1")).to_dict() == {"person": "maya", "role": "product", "domain": "product", "fallback": False}
    assert r.route(g.get("D-1")).person == "priya"


def test_unroutable_falls_back_to_the_dri():
    g = graph([rec("G-1", domain="design")] + people(dri="chandra", engg="priya"))
    route = Router(g).route(g.get("G-1"))
    assert (route.person, route.role, route.fallback) == ("chandra", "dri", True)


def test_a_task_scoped_assignment_wins_for_what_blocks_that_task():
    task = rec("T-1", goal="g", repo="r", template="t", implements=[], covers=[])
    scoped = rec("A-9", person="omar", role="engg", scope=["T-1"])
    g = graph([task, scoped, rec("G-1", domain="engg", blocks=["T-1"]), rec("G-2", domain="engg")] + people(dri="chandra", engg="priya"))
    r = Router(g)
    assert r.route(g.get("G-1")).person == "omar"
    assert r.route(g.get("G-2")).person == "priya"
    assert r.route(g.get("T-1")).person == "omar"


def test_review_items_take_the_cause_domain_when_the_target_has_none():
    g = graph([rec("AC-1", text="a"), rec("G-1", domain="product")] + people(dri="chandra", engg="priya", product="maya"))
    assert Router(g).route(g.get("AC-1"), g.get("G-1")).person == "maya"
    assert Router(g).route(g.get("AC-1")).person == "chandra"
