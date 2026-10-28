from datetime import datetime
from typing import Optional


def to_iso(dt: Optional[datetime]) -> Optional[str]:
    """Serialize a UTC-naive datetime to an ISO-8601 string with a trailing Z.

    Mirrors the old API's `Date.toISOString()` output so response shapes match.
    """
    if dt is None:
        return None
    return dt.isoformat() + "Z"
