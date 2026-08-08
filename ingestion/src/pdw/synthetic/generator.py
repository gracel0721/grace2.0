"""Synthetic data generator (spec §28).

Produces realistic GitHub repositories + commits and Google Calendar events that
stand in for the real connector layer. The output is deterministic for a given
reference date and RNG seed, so tests are stable and ``make seed`` is safe to
re-run (the loader upserts on natural keys, spec §12/§13).

The dataset includes (spec §28): multiple repositories, several months of
commits, multiple projects, calendar events across categories, and a mix of
active and inactive (stale) projects.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from .categorize import categorize

SEED = 42
DAYS_BACK = 90
TZ = ZoneInfo("America/New_York")

AUTHORS = [
    ("Grace Leverett", "grace@example.com"),
    ("Ada Lovelace", "ada@example.com"),
]

LANGUAGES = ["Python", "TypeScript", "Go", "Rust", "JavaScript", "Ruby", "Kotlin"]

# (name, owner, language, archived, first_active_offset_days_ago)
# archived repos are stale (no commits in the recent window).
REPO_SPECS = [
    ("personal-data-warehouse", "gvleverett", "Python", False, 120),
    ("explain-error", "gvleverett", "TypeScript", False, 200),
    ("codebase-rag", "gvleverett", "Go", False, 75),
    ("dotfiles", "gvleverett", "Shell", False, 250),
    ("legacy-crm", "acme", "Ruby", True, 220),
    ("analytics-pipeline", "acme", "Python", False, 95),
    ("mobile-app", "acme", "Kotlin", True, 210),
]

COMMIT_MESSAGES = [
    "feat: add ingestion scaffold",
    "fix: handle null payload in normalize",
    "refactor: split staging models",
    "chore: bump dependencies",
    "docs: update data model",
    "test: cover upsert idempotency",
    "perf: index raw tables on source_id",
    "ci: add dbt build step",
    "wip: incremental cursor logic",
    "fix: timezone handling in staging",
    "feat: synthetic calendar generator",
    "refactor: consolidate db helpers",
    "chore: lint with ruff",
    "feat: mart_daily_activity model",
    "fix: dedupe commits by sha",
]

# Calendar title templates by category (used to exercise categorize()).
CALENDAR_TEMPLATES = {
    "meeting": [
        "Daily standup", "Weekly sync", "Sprint planning", "1:1 with manager",
        "Code review", "Retrospective", "Architecture review", "Demo session",
        "Triage", "All-hands", "Interview: backend candidate",
    ],
    "learning": [
        "Reading: Designing Data-Intensive Apps", "dbt workshop",
        "Rust tutorial", "Pair programming session", "Online course: SQL",
    ],
    "personal": [
        "Lunch break", "Gym", "Dentist appointment", "Coffee with friend",
        "Errand", "Doctor appointment",
    ],
    "work": [
        "Focus: ingestion refactor", "Deep work: dbt models",
        "Inbox zero", "Draft design doc", "Investigate bug report",
    ],
    "other": [
        "OOO", "Holiday", "Focus block", "No meetings",
    ],
}

# Weekday commit/activity weights: Tue highest, Fri lowest (spec §20/§28).
WEEKDAY_WEIGHTS = [0.7, 1.0, 1.3, 1.1, 0.6, 0.2, 0.1]  # Mon..Sun


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


@dataclass
class SyntheticDataset:
    repos: list[Repo] = field(default_factory=list)
    commits: list[Commit] = field(default_factory=list)
    calendar_events: list[CalendarEvent] = field(default_factory=list)


def _sha(rng: random.Random) -> str:
    return rng.randbytes(20).hex()


def _generate_repos(rng: random.Random, anchor: datetime) -> list[Repo]:
    repos: list[Repo] = []
    for idx, (name, owner, language, archived, offset) in enumerate(REPO_SPECS):
        created = anchor - timedelta(days=offset + rng.randint(0, 45))
        repos.append(
            Repo(
                source_id=f"{owner}/{name}",
                github_repository_id=100000 + idx,
                name=name,
                owner=owner,
                full_name=f"{owner}/{name}",
                language=language,
                created_at=created,
                archived=archived,
            )
        )
    return repos


def _generate_commits(
    rng: random.Random, repos: list[Repo], anchor: datetime
) -> list[Commit]:
    commits: list[Commit] = []
    for repo in repos:
        # Stale/archived repos stop committing 30+ days before the anchor.
        active_until = anchor - timedelta(days=30) if repo.archived else anchor
        for d in range(DAYS_BACK):
            day = anchor - timedelta(days=DAYS_BACK - d)
            if day > active_until:
                continue
            weekday = day.weekday()
            # Probability of any activity this day, weighted by weekday.
            if rng.random() > 0.35 * WEEKDAY_WEIGHTS[weekday]:
                continue
            n_commits = rng.choices([1, 2, 3], weights=[5, 3, 1])[0]
            for _ in range(n_commits):
                author_name, author_email = rng.choice(AUTHORS)
                hour = rng.randint(8, 18)
                minute = rng.randint(0, 59)
                committed_at = day.replace(
                    hour=hour, minute=minute, second=0, tzinfo=UTC
                )
                sha = _sha(rng)
                commits.append(
                    Commit(
                        source_id=f"{repo.full_name}:{sha}",
                        repository_source_id=repo.source_id,
                        commit_sha=sha,
                        author_name=author_name,
                        author_email=author_email,
                        committed_at=committed_at,
                        additions=rng.randint(1, 400),
                        deletions=rng.randint(0, 200),
                        message=rng.choice(COMMIT_MESSAGES),
                    )
                )
    return commits


def _generate_calendar(
    rng: random.Random, anchor: datetime
) -> list[CalendarEvent]:
    events: list[CalendarEvent] = []
    seq = 0
    for d in range(DAYS_BACK):
        day = anchor - timedelta(days=DAYS_BACK - d)
        weekday = day.weekday()
        # Weekdays: 1-4 events; weekends: 0-1 event.
        if weekday < 5:
            n_events = rng.choices([0, 1, 2, 3, 4], weights=[1, 3, 4, 3, 1])[0]
        else:
            n_events = rng.choices([0, 1], weights=[6, 1])[0]
        hour = 9
        for _ in range(n_events):
            seq += 1
            category = rng.choices(
                list(CALENDAR_TEMPLATES.keys()),
                weights=[5, 2, 2, 3, 1],  # meeting-heavy work calendar
            )[0]
            title = rng.choice(CALENDAR_TEMPLATES[category])
            # Meetings: 30-60 min; focus/learning: 60-120 min; personal: 30-60.
            if category in ("meeting", "personal"):
                duration = rng.choice([30, 45, 60])
            else:
                duration = rng.choice([60, 90, 120])
            start = day.replace(
                hour=hour, minute=rng.choice([0, 15, 30, 45]), tzinfo=TZ
            )
            hour = min(hour + duration // 60 + 1, 18)
            end = start + timedelta(minutes=duration)
            attendees = (
                rng.randint(2, 8) if category == "meeting" else rng.randint(0, 2)
            )
            events.append(
                CalendarEvent(
                    source_id=f"evt_{seq}",
                    calendar_id="grace@example.com",
                    title=title,
                    start_at=start,
                    end_at=end,
                    timezone=str(TZ),
                    attendees_count=attendees,
                    status="confirmed",
                    category=categorize(title),
                )
            )
    return events


def generate(
    *, seed: int = SEED, anchor: datetime | None = None
) -> SyntheticDataset:
    """Generate a deterministic synthetic dataset.

    ``anchor`` defaults to the current UTC midnight so the demo always looks
    recent; the RNG seed makes output deterministic for a given anchor.
    """
    if anchor is None:
        anchor = datetime.now(UTC).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
    rng = random.Random(seed)
    repos = _generate_repos(rng, anchor)
    commits = _generate_commits(rng, repos, anchor)
    calendar_events = _generate_calendar(rng, anchor)
    return SyntheticDataset(
        repos=repos, commits=commits, calendar_events=calendar_events
    )