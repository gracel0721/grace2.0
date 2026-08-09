"""Unit tests for the Gmail API client (spec §23, §26).

Covers list pagination + the metadata-only get (format=metadata with a restricted
metadataHeaders list — the body is never requested).
"""

from pdw.connectors.base import HttpClient
from pdw.connectors.gmail import METADATA_HEADERS, GmailClient
from tests.fakes import FakeHttpClient, FakeResponse


def _stub(i: int) -> dict:
    return {"id": f"m{i}", "threadId": "t1"}


def _full(i: int) -> dict:
    return {
        "id": f"m{i}",
        "threadId": "t1",
        "internalDate": "1717588800000",
        "snippet": f"preview {i}",
        "payload": {"headers": [{"name": "From", "value": "a@x"}]},
    }


def test_list_messages_paginates_via_next_page_token():
    fake = FakeHttpClient()
    fake.add(
        "GET",
        "/users/me/messages",
        FakeResponse(
            json_data={"messages": [_stub(0), _stub(1)], "nextPageToken": "tok2"}
        ),
        FakeResponse(json_data={"messages": [_stub(2)]}),  # no nextPageToken -> stop
    )
    client = GmailClient("access", http=HttpClient(fake))

    pages = list(client.list_messages())

    assert len(pages) == 2
    assert len(pages[0]) == 2
    assert len(pages[1]) == 1
    params = fake.params_for("/users/me/messages")
    assert "pageToken" not in params[0]
    assert params[1]["pageToken"] == "tok2"
    assert params[0]["maxResults"] == 500


def test_list_messages_passes_q_filter():
    fake = FakeHttpClient().add(
        "GET", "/users/me/messages", FakeResponse(json_data={"messages": []})
    )
    client = GmailClient("access", http=HttpClient(fake))

    list(client.list_messages(q="after:2024/06/05"))

    params = fake.params_for("/users/me/messages")[0]
    assert params["q"] == "after:2024/06/05"


def test_list_messages_no_q_when_none():
    fake = FakeHttpClient().add(
        "GET", "/users/me/messages", FakeResponse(json_data={"messages": []})
    )
    client = GmailClient("access", http=HttpClient(fake))

    list(client.list_messages(q=None))

    params = fake.params_for("/users/me/messages")[0]
    assert "q" not in params


def test_get_message_is_metadata_only():
    """get_message must request format=metadata + the restricted header list,
    so the body is not transmitted (spec §23)."""
    fake = FakeHttpClient().add(
        "GET", "/users/me/messages/m1", FakeResponse(json_data=_full(1))
    )
    client = GmailClient("access", http=HttpClient(fake))

    client.get_message("m1")

    _, url, kwargs = fake.requests[0]
    assert url.endswith("/users/me/messages/m1")
    params = kwargs.get("params") or {}
    assert params["format"] == "metadata"
    # metadataHeaders is a repeated query param -> httpx carries it as a list.
    assert set(params["metadataHeaders"]) == set(METADATA_HEADERS)
    assert set(params["metadataHeaders"]) == {"From", "To", "Subject", "Date"}


def test_fetch_messages_lists_then_gets_each():
    """The connector lists stubs, then fetches each message metadata-only.

    The per-id GET routes are registered before the list route because the fake
    matches by substring: "/users/me/messages" is contained in
    "/users/me/messages/m0", so the more specific routes must be iterated first.
    """
    from pdw.connectors.gmail import GmailConnector

    fake = FakeHttpClient()
    # per-id GETs first (see docstring), then the list route.
    fake.add("GET", "/users/me/messages/m0", FakeResponse(json_data=_full(0)))
    fake.add("GET", "/users/me/messages/m1", FakeResponse(json_data=_full(1)))
    fake.add(
        "GET",
        "/users/me/messages",
        FakeResponse(json_data={"messages": [_stub(0), _stub(1)]}),
    )
    connector = GmailConnector(GmailClient("access", http=HttpClient(fake)))

    emails = connector.fetch_messages(after="2024/06/01")

    assert len(emails) == 2
    assert emails[0].source_id == "m0"
    assert emails[1].source_id == "m1"
    # the list request carried q=after:2024/06/01
    list_params = fake.params_for("/users/me/messages")[0]
    assert list_params["q"] == "after:2024/06/01"