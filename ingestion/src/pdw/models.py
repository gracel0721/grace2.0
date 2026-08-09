"""Normalized record models shared across the ingestion layer (spec §8).

These dataclasses are the in-memory contract between the connectors (GitHub,
Google Calendar, synthetic) and the pipeline loaders. Keeping them in a shared
module means ``connectors/`` and ``pipeline/`` never depend on ``synthetic/``
— the dependency direction is ``synthetic -> models <- connectors``.

Each record carries a ``raw_payload`` dict holding the original source JSON (or,
for synthetic data, a constructed stand-in) so the loaders can store the
faithful upstream payload as JSONB (spec §8 "store the original API payload
where practical").
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Repo:
    source_id: str
    github_repository_id: int
    name: str
    owner: str
    full_name: str
    language: str
    created_at: datetime
    archived: bool
    raw_payload: dict = field(default_factory=dict)


@dataclass
class Commit:
    source_id: str
    repository_source_id: str
    commit_sha: str
    author_name: str
    author_email: str
    committed_at: datetime
    additions: int
    deletions: int
    message: str
    raw_payload: dict = field(default_factory=dict)


@dataclass
class CalendarEvent:
    source_id: str
    calendar_id: str
    title: str
    start_at: datetime
    end_at: datetime
    timezone: str
    attendees_count: int
    status: str
    category: str
    raw_payload: dict = field(default_factory=dict)


@dataclass
class PullRequest:
    """A GitHub pull request (normalized from the issues endpoint, which
    returns PRs alongside issues — distinguished by the ``pull_request`` key)."""

    source_id: str  # node_id
    repository_source_id: str  # repo full_name (FK to Repo.source_id)
    number: int
    title: str
    state: str
    author: str | None
    created_at: datetime
    updated_at: datetime
    closed_at: datetime | None
    merged_at: datetime | None
    is_draft: bool
    comments_count: int
    raw_payload: dict = field(default_factory=dict)


@dataclass
class Issue:
    """A GitHub issue (an item from the issues endpoint with no
    ``pull_request`` key)."""

    source_id: str  # node_id
    repository_source_id: str  # repo full_name (FK to Repo.source_id)
    number: int
    title: str
    state: str
    state_reason: str | None
    author: str | None
    created_at: datetime
    updated_at: datetime
    closed_at: datetime | None
    comments_count: int
    raw_payload: dict = field(default_factory=dict)


@dataclass
class Email:
    """A Gmail message stored **metadata only** (spec §3, §23): the From/To/
    Subject/Date headers and the ``snippet`` preview — never the body.

    ``date`` is the server receive time derived from Gmail's ``internalDate``
    (epoch milliseconds), which is always present and timezone-safe. The
    connector cursor advances to the newest ``date`` seen.
    """

    source_id: str  # Gmail message id
    thread_id: str
    sender: str  # From header
    recipients: str  # To header (comma-joined when multiple)
    subject: str
    date: datetime  # internalDate (ms) -> datetime
    snippet: str  # ~200-char preview, NOT the message body
    raw_payload: dict = field(default_factory=dict)


@dataclass
class TrackPlay:
    """A recently-played Spotify track (spec §6).

    The Spotify recently-played endpoint returns items with no stable ``id`` of
    their own, so the natural key is ``(track_id, played_at)`` — the same track
    played at different times is a distinct play. The incremental cursor is
    ``played_at`` expressed as **epoch milliseconds** (Spotify's ``after``
    parameter is ms, not seconds — see connectors/spotify.py).
    """

    source_id: str  # "{track_id}:{played_at_iso}" — unique per play
    played_at: datetime
    track_id: str
    track_name: str
    artists: str  # comma-joined artist names
    raw_payload: dict = field(default_factory=dict)
