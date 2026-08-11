"""Application configuration loaded from environment variables.

Only ``DATABASE_URL`` is required to run the synthetic pipeline. Missing
required configuration raises a clear error rather than an obscure stack trace
(spec §7).
"""

from __future__ import annotations

from pathlib import Path

from pydantic import Field, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict

# The .env file lives at the monorepo root (two packages above this module).
_REPO_ROOT = Path(__file__).resolve().parents[3]
_ENV_FILE = _REPO_ROOT / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        # Priority: System Environment Variables > .env file
        env_file=str(_ENV_FILE) if _ENV_FILE.exists() else None,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Primary connection string used by the local uv-run ingestion app.
    database_url: str = Field(..., description="PostgreSQL connection string")

    # Name of the test database used by integration tests.
    test_database_url: str | None = Field(
        default=None, description="Connection string for the test database"
    )

    # --- Real connector credentials (all optional; spec §7, §23) ----------
    # Only required when running `pdw sync github` / `pdw sync calendar`.
    # The synthetic pipeline (`pdw seed`) needs none of these.
    github_token: str | None = Field(
        default=None, description="GitHub personal access token (PAT)"
    )
    google_client_id: str | None = Field(
        default=None, description="Google OAuth client ID"
    )
    google_client_secret: str | None = Field(
        default=None, description="Google OAuth client secret"
    )
    google_refresh_token: str | None = Field(
        default=None, description="Google OAuth refresh token"
    )
    google_calendar_id: str = Field(
        default="primary", description="Calendar ID to sync (default: primary)"
    )
    # Spotify (PKCE; no client secret — spec §23). The user creates a Spotify app,
    # sets SPOTIFY_CLIENT_ID, then `pdw auth spotify` writes SPOTIFY_REFRESH_TOKEN.
    spotify_client_id: str | None = Field(
        default=None, description="Spotify OAuth client ID (PKCE app)"
    )
    spotify_refresh_token: str | None = Field(
        default=None, description="Spotify OAuth refresh token"
    )

    @classmethod
    def load(cls) -> Settings:
        try:
            return cls()
        except ValidationError as exc:  # pragma: no cover - exercised via CLI
            fields = ", ".join(
                sorted(".".join(str(p) for p in err["loc"]) for err in exc.errors())
            )
            raise SystemExit(
                "Configuration error: missing or invalid environment variables "
                f"({fields}). Copy .env.example to .env and fill in the values."
            ) from exc


def get_settings() -> Settings:
    """Return a fresh Settings instance populated from the environment."""
    return Settings.load()


def env_file() -> Path:
    """Absolute path to the local .env (repo root). Never committed."""
    return _ENV_FILE
