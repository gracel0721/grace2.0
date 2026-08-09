"""Connector primitives: exceptions, HTTP wrapper, pagination (spec §25).

The HTTP wrapper is a thin layer over ``httpx`` that converts non-2xx responses
and transport errors into the typed exception hierarchy below. The client is
**injectable** so tests pass a fake client (no network, no extra test deps).

Error strategy (spec §25):
  * 401 / invalid_grant  -> AuthError       (abort, no retry)
  * rate limit exhausted  -> RateLimitError  (abort, no sleep-retry, spec §33)
  * transport failure     -> NetworkError    (one retry, then abort)
  * other 4xx/5xx         -> ApiError
  * bad record shape      -> MalformedRecordError (skip + count, do not abort)
"""

from __future__ import annotations

import time
from typing import Any

import httpx


class ConnectorError(Exception):
    """Base class for all connector failures."""


class AuthError(ConnectorError):
    """Authentication failed (bad token, revoked refresh token)."""


class RateLimitError(ConnectorError):
    """The API rate limit is exhausted."""


class NetworkError(ConnectorError):
    """A transport-level failure (timeout, connection reset)."""


class ApiError(ConnectorError):
    """A non-auth, non-rate-limit API error (4xx/5xx)."""

    def __init__(self, message: str, *, status_code: int) -> None:
        super().__init__(message)
        self.status_code = status_code


class MalformedRecordError(ConnectorError):
    """A single API record could not be normalized (skip + count)."""


class HttpClient:
    """Thin httpx wrapper with retry + typed error translation.

    ``client`` is injectable: production passes ``httpx.Client(...)``, tests
    pass a fake exposing ``get``/``post`` returning objects with ``status_code``,
    ``headers``, and ``json()``.
    """

    def __init__(self, client: Any, *, max_retries: int = 1) -> None:
        self._client = client
        self._max_retries = max_retries

    def get(self, url: str, *, headers: dict | None = None, **params: Any) -> Any:
        return self._request("GET", url, params=params or None, headers=headers)

    def post(
        self,
        url: str,
        *,
        data: dict | None = None,
        json: Any = None,
        headers: dict | None = None,
    ) -> Any:
        return self._request("POST", url, data=data, json=json, headers=headers)

    def _request(self, method: str, url: str, **kwargs: Any) -> Any:
        last_exc: Exception | None = None
        for attempt in range(self._max_retries + 1):
            try:
                resp = self._client.request(method, url, **kwargs)
            except httpx.RequestError as exc:  # transport failure
                last_exc = exc
                if attempt < self._max_retries:
                    time.sleep(2)
                    continue
                raise NetworkError(f"request to {url} failed: {exc}") from exc
            self._raise_for_status(resp, url)
            return resp
        # Should be unreachable; the loop either returns or raises above.
        raise NetworkError(f"request to {url} failed: {last_exc}")  # pragma: no cover

    @staticmethod
    def _raise_for_status(resp: Any, url: str) -> None:
        status = resp.status_code
        if 200 <= status < 300:
            return
        # Rate limit must be checked before the 401/403 auth branch: GitHub
        # returns 403 with X-RateLimit-Remaining: 0 when the limit is hit.
        remaining = resp.headers.get("X-RateLimit-Remaining") if resp.headers else None
        if remaining == "0" or status == 429:
            reset = resp.headers.get("X-RateLimit-Reset") if resp.headers else None
            raise RateLimitError(
                f"rate limit exhausted for {url}"
                + (f" (resets at {reset})" if reset else "")
            )
        if status in (401, 403):
            raise AuthError(f"authentication failed ({status}) for {url}")
        raise ApiError(f"{status} from {url}", status_code=status)
