"""Base response schema for standardizing API responses.

All responses expose snake_case fields internally but serialize to camelCase
JSON (FastAPI serializes response models with `by_alias=True` by default),
matching the frontend contract.
"""

from typing import Any

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class BaseResponse(BaseModel):
    """Base class for all response schemas."""

    model_config = ConfigDict(
        from_attributes=True,
        alias_generator=to_camel,
        populate_by_name=True,
    )

    @classmethod
    def from_domain(cls, domain_model: Any) -> "BaseResponse":
        """Convert a domain/ORM model to a response schema."""
        return cls.model_validate(domain_model)

    def to_dict(self) -> dict:
        return self.model_dump(by_alias=True, exclude_none=True)
