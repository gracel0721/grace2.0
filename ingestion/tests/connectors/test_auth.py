"""Unit tests for the Google OAuth helpers (spec §23, §26).

The interactive flow (browser + loopback server) isn't unit-tested, but the
pure helpers that build the auth URL and the PKCE pair are.
"""

import base64
import hashlib
from urllib.parse import parse_qs, urlparse

from pdw.connectors.auth import (
    CALENDAR_READONLY_SCOPE,
    _pkce_pair,
    build_auth_url,
)


def test_pkce_challenge_is_s256_of_verifier():
    verifier, challenge = _pkce_pair()
    expected = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest())
        .rstrip(b"=")
        .decode("ascii")
    )
    assert challenge == expected
    assert 43 <= len(verifier) <= 128  # RFC 7636 verifier length


def test_build_auth_url_contains_required_params():
    verifier, challenge = _pkce_pair()
    url = build_auth_url(
        "cid-123", "http://localhost:8787", challenge, CALENDAR_READONLY_SCOPE
    )
    parsed = urlparse(url)
    params = parse_qs(parsed.query)

    assert parsed.netloc == "accounts.google.com"
    assert params["client_id"] == ["cid-123"]
    assert params["redirect_uri"] == ["http://localhost:8787"]
    assert params["response_type"] == ["code"]
    assert params["scope"] == [CALENDAR_READONLY_SCOPE]
    assert params["access_type"] == ["offline"]  # request a refresh token
    assert params["prompt"] == ["consent"]  # force a refresh token return
    assert params["code_challenge"] == [challenge]
    assert params["code_challenge_method"] == ["S256"]
