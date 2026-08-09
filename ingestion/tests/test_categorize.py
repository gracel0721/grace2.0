"""Unit tests for calendar categorization (spec §11, §26)."""

from pdw.synthetic.categorize import CATEGORIES, categorize


def test_meeting_keywords():
    assert categorize("Daily standup") == "meeting"
    assert categorize("1:1 with manager") == "meeting"
    assert categorize("Sprint planning") == "meeting"
    assert categorize("Architecture review") == "meeting"
    assert categorize("Retrospective") == "meeting"


def test_learning_keywords():
    assert categorize("dbt workshop") == "learning"
    assert categorize("Rust tutorial") == "learning"
    assert categorize("Pair programming session") == "learning"


def test_personal_keywords():
    assert categorize("Lunch break") == "personal"
    assert categorize("Dentist appointment") == "personal"
    assert categorize("Gym") == "personal"


def test_other_keywords():
    assert categorize("OOO") == "other"
    assert categorize("Holiday") == "other"
    assert categorize("Focus block") == "other"


def test_default_is_work():
    assert categorize("Write design doc") == "work"
    assert categorize("Inbox zero") == "work"


def test_empty_title_is_other():
    assert categorize("") == "other"
    assert categorize(None) == "other"


def test_all_categories_covered():
    # The generator should be able to produce every accepted category.
    produced = {
        categorize(t)
        for t in [
            "Daily standup",
            "dbt workshop",
            "Lunch break",
            "OOO",
            "Write design doc",
        ]
    }
    assert produced.issubset(set(CATEGORIES))
