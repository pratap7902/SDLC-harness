"""POST /api/initiatives/{id}/test-runs/junit — CI posts a JUnit report for a task at a sha."""

from typing import Annotated, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field

from app.auth.dependencies import Caller
from app.initiatives.services.junit_service import JunitService
from app.initiatives.services.record_service import RecordService

router = APIRouter(tags=["test runs"])


class JunitRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    task: str = Field(description="the task ref the run is for (T-n)")
    sha: str = Field(description="the commit the tests ran on (the PR head)")
    level: str = Field(description="unit | integration | e2e")
    run_url: str = Field(description="the CI run that produced the report")
    junit_xml: str = Field(description="the JUnit XML report, verbatim")
    environment: Optional[str] = None
    agent: Optional[str] = Field(default=None, description="which CI job / skill is posting")


@router.post("/initiatives/{initiative_id}/test-runs/junit", status_code=201)
def ingest_junit(initiative_id: int, body: JunitRequest, records: Annotated[RecordService, Depends()], actor: Caller):
    """One `test_run` bound to `sha`, with a covers row per AC named in the test names
    (`AC-3`, `AC_3`, `test_AC_3_…`). Re-posting the same report is a replay."""
    return JunitService(records).ingest(
        initiative_id, body.task, body.sha, body.level, body.run_url, body.junit_xml, actor.with_agent(body.agent or "junit"), body.environment
    )
