from datetime import UTC, datetime, timedelta

# Shifts the service clock — used only by scripts/seed_demo.py to lay down a realistic
# multi-day history. Always zero in the running service.
_offset = timedelta(0)


def utcnow() -> datetime:
    """UTC, naive (what the DB columns store)."""
    return datetime.now(UTC).replace(tzinfo=None) + _offset


def set_clock(at: datetime | None) -> None:
    """Pretend it is `at` (UTC, naive) from now on; None restores the real clock."""
    global _offset
    _offset = timedelta(0) if at is None else at - datetime.now(UTC).replace(tzinfo=None)


def iso(dt) -> str | None:
    if dt is None:
        return None
    return dt.replace(microsecond=0).isoformat() + "Z"
