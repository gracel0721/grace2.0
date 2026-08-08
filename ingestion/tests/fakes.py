"""Test doubles for connector HTTP (spec §26).

``FakeHttpClient`` duck-types the ``request`` method that ``pdw.connectors.base.
HttpClient`` calls. Routes are registered per (method, path); each call pops the
next queued response (FIFO), so multi-page sequences are easy to set up. Every
request is logged for assertions about pagination tokens and cursors.

To simulate a transport failure, queue an ``httpx.RequestError`` subclass
(e.g. ``httpx.ConnectError("boom")``) instead of a ``FakeResponse``.
"""

from __future__ import annotations

from typing import Any


class FakeResponse:
    def __init__(
        self, status_code: int = 200, json_data: Any = None, headers: dict | None = None
    ) -> None:
        self.status_code = status_code
        self._json = json_data if json_data is not None else {}
        self.headers = headers or {}

    def json(self) -> Any:
        return self._json


class FakeHttpClient:
    def __init__(self) -> None:
        self._routes: dict[tuple[str, str], list] = {}
        self.requests: list[tuple[str, str, dict]] = []

    def add(self, method: str, path: str, *responses: Any) -> FakeHttpClient:
        self._routes.setdefault((method, path), []).extend(responses)
        return self

    def request(self, method: str, url: str, **kwargs: Any) -> FakeResponse:
        self.requests.append((method, url, kwargs))
        for (m, p), responses in self._routes.items():
            if m != method:
                continue
            if url == p or p in url:
                if not responses:
                    raise AssertionError(
                        f"no queued responses left for {method} {p} (url={url})"
                    )
                resp = responses.pop(0)
                if isinstance(resp, Exception):
                    raise resp
                return resp
        raise AssertionError(f"no route registered for {method} {url}")

    # Convenience: the last request's params (for cursor/pagination assertions).
    @property
    def last_params(self) -> dict:
        return self.requests[-1][2].get("params") or {} if self.requests else {}

    def params_for(self, path: str) -> list[dict]:
        return [
            kw.get("params") or {} for _, u, kw in self.requests if path in u
        ]