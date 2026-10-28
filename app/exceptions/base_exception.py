from typing import Any, Dict, Optional


class BaseAppException(Exception):
    """
    Base exception class for all application exceptions.
    Follows RFC 9457 for error formatting.
    """

    def __init__(
        self,
        status_code: int,
        message: str,
        instance: Optional[str] = None,
        headers: Optional[Dict[str, str]] = None,
        error_code: Optional[str] = None,
        error_data: Optional[Dict[str, Any]] = None,
    ):
        self.status_code = status_code
        self.message = message
        self.instance = instance
        self.headers = headers
        self.error_code = error_code
        self.error_data = error_data or {}
