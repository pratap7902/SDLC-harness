from typing import Any, Dict, Optional

from fastapi import status

from app.exceptions.client_exception import ClientException
from app.exceptions.Enums.exception_codes import ExceptionCode


class ForbiddenException(ClientException):
    """
    Exception for authorization errors.
    """

    def __init__(
        self,
        message: str = "Forbidden",
        instance: Optional[str] = None,
        headers: Optional[Dict[str, str]] = None,
        error_code: Optional[str] = None,
        error_data: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(
            status_code=status.HTTP_403_FORBIDDEN,
            message=message,
            instance=instance,
            headers=headers,
            error_code=error_code or ExceptionCode.FORBIDDEN,
            error_data=error_data,
        )
