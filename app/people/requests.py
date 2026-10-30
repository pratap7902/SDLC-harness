from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CreatePersonRequest(_Body):
    handle: str = Field(description="what assignments name, e.g. priya")
    name: Optional[str] = None
    email: Optional[str] = None


class ResolvePeopleReviewRequest(_Body):
    action: str = Field(description="link | create | ignore")
    handle: Optional[str] = Field(default=None, description="link: the person; create: the new handle")
    name: Optional[str] = None
