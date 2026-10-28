from typing import Any, Dict, Optional

from fastapi import status

from app.exceptions.client_exception import ClientException
from app.exceptions.Enums.exception_codes import ExceptionCode


class ConflictException(ClientException):
    """409 — e.g. a write batch_id reused with different ops, a lease held by someone else."""

    def __init__(
        self,
        message: str = "Conflict",
        instance: Optional[str] = None,
        headers: Optional[Dict[str, str]] = None,
        error_code: Optional[str] = None,
        error_data: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            message=message,
            instance=instance,
            headers=headers,
            error_code=error_code or ExceptionCode.CONFLICT,
            error_data=error_data,
        )
