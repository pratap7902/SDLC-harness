"""
Exception handling for the FastAPI application.

This module defines custom exceptions that can be used throughout the application
to provide consistent error handling and responses.
"""

from app.exceptions.base_exception import BaseAppException
from app.exceptions.client_exception import ClientException
from app.exceptions.conflict_exception import ConflictException
from app.exceptions.forbidden_exception import ForbiddenException
from app.exceptions.not_found_exception import NotFoundException
from app.exceptions.rate_limit_exception import RateLimitException
from app.exceptions.server_exception import ServerException
from app.exceptions.unauthorized_exception import UnauthorizedException
from app.exceptions.validation_exception import ValidationException

__all__ = [
    "BaseAppException",
    "ClientException",
    "ConflictException",
    "ForbiddenException",
    "NotFoundException",
    "RateLimitException",
    "ServerException",
    "UnauthorizedException",
    "ValidationException",
]
