"""Structured logs: one JSON object per line on stderr. `log.info("claimed", key=…, kind=…)`.
Never pass a token, a key or a prompt body as a field."""

import json
import logging
import sys
import time

_logger = logging.getLogger("runner")
REDACT = ("token", "secret", "private_key", "authorization", "password")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        out = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created)) + f".{int(record.msecs):03d}Z",
            "level": record.levelname.lower(),
            "event": record.getMessage(),
        }
        for k, v in (getattr(record, "fields", None) or {}).items():
            out[k] = "[redacted]" if any(r in k.lower() for r in REDACT) else v
        if record.exc_info:
            out["exc"] = self.formatException(record.exc_info)
        return json.dumps(out, default=str)


def setup(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(JsonFormatter())
    _logger.handlers[:] = [handler]
    _logger.setLevel(level.upper())
    _logger.propagate = False


class _Log:
    def _emit(self, level: int, event: str, exc_info=None, **fields) -> None:
        _logger.log(level, event, exc_info=exc_info, extra={"fields": fields})

    def debug(self, event: str, **fields) -> None:
        self._emit(logging.DEBUG, event, **fields)

    def info(self, event: str, **fields) -> None:
        self._emit(logging.INFO, event, **fields)

    def warning(self, event: str, **fields) -> None:
        self._emit(logging.WARNING, event, **fields)

    def error(self, event: str, exc: bool = False, **fields) -> None:
        self._emit(logging.ERROR, event, exc_info=exc or None, **fields)


log = _Log()
