from enum import Enum


class ExceptionCode(str, Enum):
    """
    Enum for exception codes used throughout the application.

    These codes provide a standardized way to identify different types of errors
    and can be used in error responses following RFC 9457 Problem Details format.
    """

    # Client error codes (4xx)
    CLIENT_ERROR = "CLIENT_ERROR"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    UNAUTHORIZED = "UNAUTHORIZED"
    FORBIDDEN = "FORBIDDEN"
    NOT_FOUND = "NOT_FOUND"
    METHOD_NOT_ALLOWED = "METHOD_NOT_ALLOWED"
    CONFLICT = "CONFLICT"
    TOO_MANY_REQUESTS = "TOO_MANY_REQUESTS"

    # Server error codes (5xx)
    INTERNAL_SERVER_ERROR = "INTERNAL_SERVER_ERROR"
    NOT_IMPLEMENTED = "NOT_IMPLEMENTED"
    SERVICE_UNAVAILABLE = "SERVICE_UNAVAILABLE"
    INVARIANT_VIOLATED_EXCEPTION = "INVARIANT_VIOLATED_EXCEPTION"

    # Business logic error codes (custom)
    BUSINESS_RULE_VIOLATION = "BUSINESS_RULE_VIOLATION"
    DATA_INTEGRITY_ERROR = "DATA_INTEGRITY_ERROR"
    EXTERNAL_SERVICE_ERROR = "EXTERNAL_SERVICE_ERROR"
