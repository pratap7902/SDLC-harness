from typing import Any, Dict, Optional

from fastapi import status

from app.exceptions.client_exception import ClientException
from app.exceptions.Enums.exception_codes import ExceptionCode


class NotFoundException(ClientException):
    """
    Exception for resource not found errors.
    """

    def __init__(
        self,
        message: str = "Resource not found",
        instance: Optional[str] = None,
        headers: Optional[Dict[str, str]] = None,
        error_code: Optional[str] = None,
        error_data: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            message=message,
            instance=instance,
            headers=headers,
            error_code=error_code or ExceptionCode.NOT_FOUND,
            error_data=error_data,
        )
