"""Mocked HTTP for integration tests: a tiny router over httpx.MockTransport. Every
request that reaches no route fails the test — nothing leaves the process."""

import json
import re
from typing import Callable, List, Tuple

import httpx

from app.core.utils import http


class MockHttp:
    def __init__(self):
        self.routes: List[Tuple[str, re.Pattern, Callable]] = []
        self.calls: List[httpx.Request] = []

    def on(self, method: str, url_regex: str, reply):
        """reply: a dict/list (200 JSON), an httpx.Response, or fn(request) → either."""
        self.routes.insert(0, (method.upper(), re.compile(url_regex), reply))
        return self

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        for method, pattern, reply in self.routes:
            if method == request.method and pattern.search(str(request.url)):
                out = reply(request) if callable(reply) else reply
                if isinstance(out, httpx.Response):
                    return out
                return httpx.Response(200, json=out)
        raise AssertionError(f"unexpected HTTP call: {request.method} {request.url}")

    def sent(self, method: str, url_regex: str) -> List[httpx.Request]:
        return [r for r in self.calls if r.method == method and re.search(url_regex, str(r.url))]

    @staticmethod
    def body(request: httpx.Request):
        return json.loads(request.content or b"null")


def install(monkeypatch) -> MockHttp:
    mock = MockHttp()
    monkeypatch.setattr(http, "TRANSPORT", httpx.MockTransport(mock.handler))
    return mock
