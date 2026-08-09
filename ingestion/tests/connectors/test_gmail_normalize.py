"""Unit tests for Gmail message normalization (spec §3, §23, §26).

Metadata only: From/To/Subject/Date headers + snippet, never the body. ``date``
comes from Gmail's ``internalDate`` (epoch ms), not the (optional) Date header.
"""

from datetime import UTC, datetime

from pdw.connectors.gmail import GmailConnector

# `_normalize_message` is a static method with no client dependency.
CONNECTOR = GmailConnector(client=None)  # type: ignore[arg-type]


def _msg(msg_id="m1", internal="1717588800000", headers=None, snippet="preview"):
    return {
        "id": msg_id,
        "threadId": "t1",
        "internalDate": internal,
        "snippet": snippet,
        "payload": {"headers": headers or []},
    }


def test_normalize_parses_headers_and_internal_date():
    raw = _msg(
        headers=[
            {"name": "From", "value": "Ada <ada@x>"},
            {"name": "To", "value": "me@x"},
            {"name": "Subject", "value": "Hello"},
            {"name": "Date", "value": "Tue, 04 Jun 2024 12:00:00 +0000"},
        ]
    )
    email = CONNECTOR._normalize_message(raw)
    assert email.source_id == "m1"
    assert email.thread_id == "t1"
    assert email.sender == "Ada <ada@x>"
    assert email.recipients == "me@x"
    assert email.subject == "Hello"
    # internalDate 1717588800000 ms == 2024-06-05T12:00:00Z
    assert email.date == datetime(2024, 6, 5, 12, 0, tzinfo=UTC)
    assert email.snippet == "preview"
    assert email.raw_payload is raw


def test_normalize_uses_internal_date_not_date_header():
    """`date` must come from internalDate (server time), not the Date header,
    which may be absent or in an arbitrary sender timezone."""
    raw = _msg(
        internal="1717588800000",  # 2024-06-05T12:00:00Z
        headers=[{"name": "Date", "value": "Wed, 05 Jun 2024 07:00:00 -0500"}],
    )
    email = CONNECTOR._normalize_message(raw)
    assert email.date == datetime(2024, 6, 5, 12, 0, tzinfo=UTC)


def test_normalize_missing_headers_default_to_empty():
    raw = _msg(headers=[], snippet="")
    email = CONNECTOR._normalize_message(raw)
    assert email.sender == ""
    assert email.recipients == ""
    assert email.subject == ""
    assert email.snippet == ""


def test_normalize_no_payload_is_safe():
    raw = {"id": "m9", "threadId": "t9", "internalDate": "1717588800000", "snippet": "s"}
    email = CONNECTOR._normalize_message(raw)
    assert email.sender == ""
    assert email.subject == ""


def test_normalize_missing_thread_id_defaults_empty():
    raw = {"id": "m9", "internalDate": "1717588800000", "snippet": "s", "payload": {}}
    email = CONNECTOR._normalize_message(raw)
    assert email.thread_id == ""