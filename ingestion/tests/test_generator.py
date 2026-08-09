"""Unit tests for the synthetic generator (spec §26, §28)."""

from datetime import UTC

from pdw.synthetic import generate
from pdw.synthetic.categorize import CATEGORIES


def test_deterministic():
    a = generate()
    b = generate()
    assert [r.source_id for r in a.repos] == [r.source_id for r in b.repos]
    assert [c.source_id for c in a.commits] == [c.source_id for c in b.commits]
    assert [e.source_id for e in a.calendar_events] == [
        e.source_id for e in b.calendar_events
    ]


def test_repo_count():
    assert len(generate().repos) == 7


def test_commit_count_reasonable():
    n = len(generate().commits)
    assert 50 < n < 1000


def test_event_count_reasonable():
    n = len(generate().calendar_events)
    assert 50 < n < 1000


def test_categories_valid_and_varied():
    cats = {e.category for e in generate().calendar_events}
    assert cats.issubset(set(CATEGORIES))
    assert len(cats) >= 3  # exercise a spread of categories


def test_has_active_and_stale_repos():
    """Archived repos must have no commits in the recent window (spec §28)."""
    from datetime import datetime, timedelta

    ds = generate()
    anchor = datetime.now(UTC)
    archived = [r for r in ds.repos if r.archived]
    assert len(archived) >= 2
    for repo in archived:
        recent = [
            c
            for c in ds.commits
            if c.repository_source_id == repo.source_id
            and c.committed_at > anchor - timedelta(days=30)
        ]
        assert recent == [], f"archived repo {repo.name} has recent commits"


def test_commit_shas_unique():
    shas = [c.commit_sha for c in generate().commits]
    assert len(shas) == len(set(shas))
