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
        env_file=str(_ENV_FILE),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Primary connection string used by the local uv-run ingestion app.
    database_url: str = Field(..., description="PostgreSQL connection string")

    # Name of the test database used by integration tests.
    test_database_url: str | None = Field(
        default=None, description="Connection string for the test database"
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