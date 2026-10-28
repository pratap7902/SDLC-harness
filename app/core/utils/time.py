from datetime import UTC, datetime


def utcnow() -> datetime:
    """UTC, naive (what the DB columns store)."""
    return datetime.now(UTC).replace(tzinfo=None)


def iso(dt) -> str | None:
    if dt is None:
        return None
    return dt.replace(microsecond=0).isoformat() + "Z"
