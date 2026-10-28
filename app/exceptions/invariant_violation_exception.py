from app.exceptions.Enums.exception_codes import ExceptionCode
from app.exceptions.server_exception import ServerException


class InvariantViolationException(ServerException):
    """
    Exception for when an invariant is violated
    """

    def __init__(self, message="Invariant violation", **kwargs):
        super().__init__(
            message=message,
            error_code=ExceptionCode.INVARIANT_VIOLATED_EXCEPTION,
            **kwargs,
        )
