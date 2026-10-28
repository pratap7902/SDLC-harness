from typing import Any, Dict, Optional

from fastapi import status

from app.exceptions.base_exception import BaseAppException
from app.exceptions.Enums.exception_codes import ExceptionCode


class ClientException(BaseAppException):
    """
    Exception for client-side errors (4xx status codes).

    Use this for errors caused by invalid client requests.
    """

    def __init__(
        self,
        message: str = "Bad request",
        instance: Optional[str] = None,
        headers: Optional[Dict[str, str]] = None,
        error_code: Optional[str] = None,
        error_data: Optional[Dict[str, Any]] = None,
        status_code: int = status.HTTP_400_BAD_REQUEST,
    ):
        super().__init__(
            status_code=status_code,
            message=message,
            instance=instance,
            headers=headers,
            error_code=error_code or ExceptionCode.CLIENT_ERROR,
            error_data=error_data,
        )
