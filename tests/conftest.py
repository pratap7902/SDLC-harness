import os

# Tests run against the blueprint under tests/fixtures/blueprint (symlinks to blueprint/:
# a test that needs a different shape points BLUEPRINT_DIR elsewhere for itself).
os.environ["BLUEPRINT_DIR"] = os.path.join(os.path.dirname(__file__), "fixtures", "blueprint")
os.environ["REVIEW_PROPAGATION"] = "true"
os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.core.database import get_primary_db  # noqa: E402
from app.mcp import server as mcp_server  # noqa: E402
from main import app  # noqa: E402
from tests.fixtures.api import Api  # noqa: E402
from tests.fixtures.database import db_session, engine, mysql_engine  # noqa: E402,F401,F811


@pytest.fixture
def client(db_session):  # noqa: F811
    """A human caller (the web UI): X-Actor tester."""
    app.dependency_overrides[get_primary_db] = lambda: db_session
    mcp_server.session_provider = lambda: db_session
    yield TestClient(app, headers={"X-Actor": "tester"})
    app.dependency_overrides.clear()
    mcp_server.session_provider = None


def _as(person: str, kind: str) -> TestClient:
    return TestClient(app, headers={"X-Actor": person, "X-Actor-Kind": kind})


@pytest.fixture
def human_client(client):
    """human_client("priya") → a TestClient acting as that human."""
    return lambda person="chandra": _as(person, "human")


@pytest.fixture
def agent_client(client):
    """An agent (the runner) — X-Actor runner-sdk, X-Actor-Kind agent."""
    return _as("runner-sdk", "agent")


@pytest.fixture
def api(client):
    return Api(app)
