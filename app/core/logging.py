"""stdlib logging (CIS used the private piperkit logger)."""

import logging

logger = logging.getLogger("srs")


class LogEvents:
    REQUEST_STARTED = "request_started"
    REQUEST_ENDED = "request_ended"
    HEALTH_CHECK = "health_check"
