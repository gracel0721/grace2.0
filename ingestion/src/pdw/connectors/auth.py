"""One-time Google OAuth 2.0 flow to obtain a refresh token (spec §23).

This is the "installed app" authorization-code flow with PKCE (S256) and a
loopback redirect. It runs once per machine to mint a ``refresh_token`` that
the Calendar connector then exchanges for short-lived access tokens in memory.

The refresh token is the only long-lived secret; it is written to the local
``.env`` (never committed, never stored in PostgreSQL — spec §7, §23).
"""

from __future__ import annotations

import base64
import hashlib
import secrets
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlencode, urlparse

import httpx

CALENDAR_READONLY_SCOPE = "https://www.googleapis.com/auth/calendar.readonly"
GMAIL_READONLY_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
SPREADSHEETS_READONLY_SCOPE = "https://www.googleapis.com/auth/spreadsheets.readonly"

# Consolidated scopes for every Google source in the warehouse (spec §23).
# The one-time `pdw auth google` flow requests all of these together so the
# single refresh token it mints is authorized for calendar, gmail, and sheets
# (job applications) without a later re-auth. Google accepts a space-delimited
# scope string in the authorization URL.
GOOGLE_SCOPES = " ".join(
    [CALENDAR_READONLY_SCOPE, GMAIL_READONLY_SCOPE, SPREADSHEETS_READONLY_SCOPE]
)
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"


def _pkce_pair() -> tuple[str, str]:
    """Return a (code_verifier, code_challenge) pair for PKCE-S256."""
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def build_auth_url(
    client_id: str, redirect_uri: str, code_challenge: str, scope: str
) -> str:
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": scope,
        "access_type": "offline",  # request a refresh token
        "prompt": "consent",  # force consent so a refresh token is always returned
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    return f"{AUTH_URL}?{urlencode(params)}"


def _wait_for_code(port: int) -> str:
    """Run a loopback HTTP server until Google redirects back with the code."""
    result: dict = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - http handler signature
            query = parse_qs(urlparse(self.path).query)
            if "error" in query:
                result["error"] = query["error"][0]
                body = b"Authorization failed. You can close this tab."
            elif "code" in query:
                result["code"] = query["code"][0]
                body = (
                    b"Authorization successful. You can close this tab and "
                    b"return to your terminal."
                )
            else:
                self.send_response(404)
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"<h2>" + body + b"</h2>")

        def log_message(self, *args: object) -> None:  # silence server logging
            pass

    server = HTTPServer(("127.0.0.1", port), Handler)
    try:
        server.handle_request()  # one request: the OAuth redirect
    finally:
        server.server_close()

    if "error" in result:
        raise RuntimeError(f"authorization denied: {result['error']}")
    if "code" not in result:
        raise RuntimeError("no authorization code received")
    return result["code"]


def exchange_code(
    client_id: str,
    client_secret: str,
    code: str,
    redirect_uri: str,
    code_verifier: str,
) -> dict:
    """Exchange an authorization code for tokens (access + refresh)."""
    resp = httpx.post(
        TOKEN_URL,
        data={
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
            "code_verifier": code_verifier,
        },
        timeout=30.0,
    )
    body = resp.json()
    if resp.status_code != 200:
        raise RuntimeError(
            f"token exchange failed ({resp.status_code}): "
            f"{body.get('error_description', body.get('error', 'unknown'))}"
        )
    if "refresh_token" not in body:
        raise RuntimeError(
            "no refresh_token in response — re-run with --force-consent, or "
            "revoke the app at https://myaccount.google.com/permissions and retry."
        )
    return body


def run_oauth_flow(
    client_id: str,
    client_secret: str,
    *,
    port: int = 8787,
    scope: str = GOOGLE_SCOPES,
    open_browser: bool = True,
) -> str:
    """Run the full one-time flow and return the refresh token."""
    verifier, challenge = _pkce_pair()
    redirect_uri = f"http://localhost:{port}"
    auth_url = build_auth_url(client_id, redirect_uri, challenge, scope)

    if open_browser:
        webbrowser.open(auth_url)
    print("\nOpen this URL in your browser if it did not open automatically:\n")
    print(f"  {auth_url}\n")
    print(f"Waiting for authorization on {redirect_uri} ...")

    code = _wait_for_code(port)
    tokens = exchange_code(client_id, client_secret, code, redirect_uri, verifier)
    return tokens["refresh_token"]
