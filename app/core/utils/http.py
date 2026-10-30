"""The one place integrations get an httpx client. Tests set TRANSPORT to an
httpx.MockTransport so no request leaves the process."""

from typing import Optional

import httpx

TRANSPORT: Optional[httpx.BaseTransport] = None
TIMEOUT = httpx.Timeout(15.0, connect=5.0)


def client(**kwargs) -> httpx.Client:
    if TRANSPORT is not None:
        kwargs["transport"] = TRANSPORT
    kwargs.setdefault("timeout", TIMEOUT)
    return httpx.Client(**kwargs)
