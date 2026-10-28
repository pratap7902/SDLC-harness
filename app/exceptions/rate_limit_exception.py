from typing import Any, Dict, Optional, Union

from fastapi import status

from app.exceptions.client_exception import ClientException
from app.exceptions.Enums.exception_codes import ExceptionCode


class RateLimitException(ClientException):
    """
    Exception for rate limit exceeded errors.
    """

    def __init__(
        self,
        message: str = "Rate limit exceeded",
        instance: Optional[str] = None,
        headers: Optional[Dict[str, str]] = None,
        error_code: Optional[str] = None,
        error_data: Optional[Dict[str, Any]] = None,
        retry_after: Optional[Union[int, str]] = None,
    ):
        headers = headers or {}
        if retry_after is not None:
            headers["Retry-After"] = str(retry_after)

        super().__init__(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            message=message,
            instance=instance,
            headers=headers,
            error_code=error_code or ExceptionCode.TOO_MANY_REQUESTS,
            error_data=error_data,
        )
