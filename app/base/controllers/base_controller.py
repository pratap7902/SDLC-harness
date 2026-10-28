class BaseController:
    """
    Base controller with common HTTP handling logic
    """

    def handle_not_found(self, message: str = "Resource not found"):
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail=message)

    def handle_bad_request(self, message: str = "Bad request"):
        from fastapi import HTTPException

        raise HTTPException(status_code=400, detail=message)
