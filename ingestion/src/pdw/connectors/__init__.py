"""External source connectors (spec §6, §25).

Each connector wraps a single HTTP API and normalizes its responses into the
shared ``pdw.models`` records. Connectors never touch the database directly —
the pipeline runner fetches records and hands them to the loaders.
"""

from .base import (
    ApiError,
    AuthError,
    ConnectorError,
    MalformedRecordError,
    NetworkError,
    RateLimitError,
)

__all__ = [
    "ApiError",
    "AuthError",
    "ConnectorError",
    "MalformedRecordError",
    "NetworkError",
    "RateLimitError",
]
