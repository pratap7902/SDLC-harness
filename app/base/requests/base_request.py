from typing import Any, Dict

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class BaseRequest(BaseModel):
    """Base class for all request schemas.

    Accepts camelCase JSON keys (matching the frontend contract) while exposing
    snake_case attributes internally. `get()` returns validated snake_case data.
    """

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="ignore",
    )

    def get(self) -> Dict[str, Any]:
        """Get validated data as a snake_case dict."""
        return self.model_dump()

    def get_set(self) -> Dict[str, Any]:
        """Only the fields the client actually sent (for partial updates)."""
        return self.model_dump(exclude_unset=True)
