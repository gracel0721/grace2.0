"""Calendar event categorization (spec §11).

Keyword rules map an event title to one of the accepted categories. The same
rules are used by the synthetic generator now and by the real Calendar
connector later, so categorization stays consistent. No ML classifier is
required for the MVP (spec §11).
"""

from __future__ import annotations

CATEGORIES = ("work", "personal", "learning", "meeting", "other")

_MEETING = (
    "sync", "standup", "stand-up", "stand up", "review", "retro", "1:1",
    "1-on-1", "1 on 1", "interview", "planning", "daily", "weekly", "meeting",
    "demo", "triage", "grooming", "sprint", "all-hands", "1:1",
)
_LEARNING = (
    "study", "course", "lecture", "tutorial", "workshop", "reading", "class",
    "training", "pairing", "pair programming",
)
_PERSONAL = (
    "dentist", "doctor", "gym", "lunch", "break", "personal", "errand",
    "haircut", "family", "dinner", "coffee",
)
_OTHER = (
    "ooo", "out of office", "holiday", "vacation", "pto", "blocker", "focus",
    "deep work", "no meetings",
)


def categorize(title: str | None) -> str:
    """Return the category for a calendar event title."""
    t = (title or "").strip().lower()
    if not t:
        return "other"
    if any(k in t for k in _OTHER):
        return "other"
    if any(k in t for k in _MEETING):
        return "meeting"
    if any(k in t for k in _LEARNING):
        return "learning"
    if any(k in t for k in _PERSONAL):
        return "personal"
    return "work"