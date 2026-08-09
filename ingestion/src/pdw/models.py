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