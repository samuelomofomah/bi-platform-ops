"""A stand-in for requests.Session that serves canned responses by URL suffix."""
from __future__ import annotations


class FakeResponse:
    def __init__(self, payload=None, status=200, headers=None, content=b""):
        self._payload, self.status_code = payload, status
        self.headers, self._content = headers or {}, content

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def iter_content(self, chunk_size=1):
        yield self._content


class FakeSession:
    def __init__(self, routes: dict):
        self.routes, self.headers, self.calls = routes, {}, []

    def _serve(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        for (m, suffix), handler in self.routes.items():
            if m == method and url.endswith(suffix):
                return handler(kwargs) if callable(handler) else handler
        return FakeResponse(status=404)

    def get(self, url, **kwargs):
        return self._serve("GET", url, **kwargs)

    def post(self, url, **kwargs):
        return self._serve("POST", url, **kwargs)
