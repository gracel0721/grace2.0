"""Unit tests for Google OAuth token refresh (spec §23, §25, §26)."""

import pytest

from pdw.connectors.base import AuthError, HttpClient
from pdw.connectors.calendar import GoogleTokenRefresher
from tests.fakes import FakeHttpClient, FakeResponse


def test_refresh_returns_access_token():
    fake = FakeHttpClient().add(
        "POST", "/token",
        FakeResponse(json_data={"access_token": "abc123", "expires_in": 3600}),
    )
    refresher = GoogleTokenRefresher("cid", "secret", http=HttpClient(fake))

    token = refresher.refresh("refresh-token")

    assert token == "abc123"
    # the refresh request posts the grant body
    method, url, kwargs = fake.requests[0]
    assert method == "POST"
    data = kwargs.get("data", {})
    assert data["grant_type"] == "refresh_token"
    assert data["refresh_token"] == "refresh-token"


def test_invalid_grant_raises_auth_error():
    """A 400 invalid_grant means the refresh token is revoked (spec §25)."""
    fake = FakeHttpClient().add(
        "POST", "/token",
        FakeResponse(status_code=400, json_data={"error": "invalid_grant"}),
    )
    refresher = GoogleTokenRefresher("cid", "secret", http=HttpClient(fake))

    with pytest.raises(AuthError):
        refresher.refresh("bad-token")