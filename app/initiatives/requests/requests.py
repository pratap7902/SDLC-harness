"""Request bodies (snake_case JSON; unknown keys are ignored except inside write ops)."""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class _Body(BaseModel):
    model_config = ConfigDict(extra="ignore")


class StartFeatureRequest(_Body):
    title: str
    requirement: str = Field(description="markdown — the requirement the feature starts from")
    dri: str
    engg: str
    slug: Optional[str] = None
    work_item_url: Optional[str] = Field(default=None, description="Azure DevOps work item link (optional)")
    product: Optional[str] = None
    design: Optional[str] = None
    qa: Optional[str] = None
    prd_refs: Optional[List[str]] = None


class RepinRequest(_Body):
    requirement: str
    work_item_url: Optional[str] = None


class WriteRequest(_Body):
    ops: List[Dict[str, Any]]
    batch_id: Optional[str] = None
    agent: Optional[str] = Field(default=None, description="which agent / skill is writing")


class AnswerGapRequest(_Body):
    answer: Optional[str] = ""
    choice: Optional[str] = None


class RuleDecisionRequest(_Body):
    verdict: str
    rationale: str


class ApprovalRequest(_Body):
    target: str = Field(description="'draft', a task ref (T-n), or a manual AC ref")
    role: str = Field(description="dri (draft) · engg (task) · qa (manual AC)")
    at_sha: Optional[str] = None
    note: Optional[str] = None


class SignRequest(_Body):
    at_sha: str


class RetireRequest(_Body):
    because: str


class ResolveReviewRequest(_Body):
    resolution: str = Field(description="upheld | revised | dismissed")
    note: str


class ClaimRequest(_Body):
    item_key: str
    ttl_min: Optional[int] = None


class HeartbeatRequest(_Body):
    ttl_min: Optional[int] = None


class DeployGuardRequest(_Body):
    initiative: str
    task: str
    sha: str
    environment: str
