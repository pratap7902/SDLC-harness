from typing import Any, Dict, Optional

from fastapi import status

from app.exceptions.base_exception import BaseAppException
from app.exceptions.Enums.exception_codes import ExceptionCode


class ServerException(BaseAppException):
    """
    Exception for server-side errors (5xx status codes).

    Use this for unexpected errors that occur on the server side.
    """

    def __init__(
        self,
        message: str = "Something went wrong. Try again.",
        instance: Optional[str] = None,
        headers: Optional[Dict[str, str]] = None,
        error_code: Optional[str] = None,
        error_data: Optional[Dict[str, Any]] = None,
        status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR,
    ):
        super().__init__(
            status_code=status_code,
            message=message,
            instance=instance,
            headers=headers,
            error_code=error_code or ExceptionCode.INTERNAL_SERVER_ERROR,
            error_data=error_data,
        )
