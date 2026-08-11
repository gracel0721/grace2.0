from fastapi import FastAPI
from mangum import Mangum
import sys
import os
import json
from datetime import datetime, UTC

# Add the ingestion source directory to the path so we can import pdw
sys.path.append(os.path.join(os.getcwd(), "ingestion/src"))

from pdw.config import get_settings
from pdw.pipeline import runner
from pdw.connectors.base import HttpClient
from pdw.connectors.github import GitHubClient, GitHubConnector, GitHubIssuesConnector
from pdw.connectors.calendar import CalendarClient, CalendarConnector
from pdw.connectors.gmail import GmailClient, GmailConnector
from pdw.connectors.spotify import (
    SpotifyTokenRefresher,
    SpotifyClient,
    SpotifyConnector
)
import httpx

app = FastAPI()

@app.get("/api/sync")
async def sync_pipeline():
    """Trigger the PDW ingestion pipeline."""
    settings = get_settings()
    url = settings.database_url

    results = {}

    try:
        # IMPORTANT: In the Vercel serverless environment,
        # the GitHubClient expects a HttpClient wrapper.
        # We create a standard httpx.Client and wrap it.
        # We MUST NOT use a base_url in the HttpClient wrapper
        # because the GitHubClient handles the base_url internally
        # via its own httpx.Client configuration.

        raw_client = httpx.Client(timeout=30.0)
        http_client = HttpClient(raw_client)

        # 1. GitHub Sync
        if settings.github_token:
            # Pass the wrapped http_client.
            # GitHubClient uses this to perform requests.
            gh_client = GitHubClient(settings.github_token, client=http_client)
            gh_conn = GitHubConnector(gh_client)
            results["github"] = runner.run_github(gh_conn, url=url).__dict__

            gh_issues_conn = GitHubIssuesConnector(gh_client)
            results["github_issues"] = runner.run_github_issues(gh_issues_conn, url=url).__dict__

        # 2. Google Calendar Sync
        if settings.google_client_id and settings.google_client_secret and settings.google_refresh_token:
            cal_client = CalendarClient(
                settings.google_client_id,
                settings.google_client_secret,
                settings.google_refresh_token,
                client=http_client
            )
            cal_conn = CalendarConnector(cal_client)
            results["calendar"] = runner.run_calendar(cal_conn, url=url).__dict__

        # 3. Gmail Sync
        if settings.google_client_id and settings.google_client_secret and settings.google_refresh_token:
            gmail_client = GmailClient(
                settings.google_client_id,
                settings.google_client_secret,
                settings.google_refresh_token,
                client=http_client
            )
            gmail_conn = GmailConnector(gmail_client)
            results["gmail"] = runner.run_gmail(gmail_conn, url=url).__dict__

        # 4. Spotify Sync
        if settings.spotify_client_id and settings.spotify_refresh_token:
            refresher = SpotifyTokenRefresher(settings.spotify_client_id, http=http_client)
            access_token = refresher.refresh(settings.spotify_refresh_token)
            spot_client = SpotifyClient(access_token, http=http_client)
            spot_conn = SpotifyConnector(spot_client)
            results["spotify"] = runner.run_spotify(spot_conn, url=url).__dict__

        return {
            "status": "success",
            "timestamp": datetime.now(UTC).isoformat(),
            "results": results
        }

    except Exception as e:
        return {
            "status": "error",
            "message": str(e)
        }

# Vercel entry point
handler = Mangum(app)
