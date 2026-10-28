from typing import Any, Dict, Optional

from fastapi import status

from app.exceptions.client_exception import ClientException
from app.exceptions.Enums.exception_codes import ExceptionCode


class UnauthorizedException(ClientException):
    """
    Unauthorized exception class for 401 authentication errors,
    """

    def __init__(
        self,
        message: str = "Unauthorized",
        instance: Optional[str] = None,
        headers: Optional[Dict[str, str]] = None,
        error_code: Optional[str] = None,
        error_data: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(
            status_code=status.HTTP_401_UNAUTHORIZED,
            message=message,
            instance=instance,
            headers=headers,
            error_code=error_code or ExceptionCode.UNAUTHORIZED,
            error_data=error_data,
        )
