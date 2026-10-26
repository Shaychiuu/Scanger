"""Offline checks for the SerpApi adapter. A fake session replaces the network."""

import json

import pytest
import requests

from scanger.serpapi import REDACTED, ProviderError, SerpApiClient

KEY = "secret-key-123"


class FakeResponse:
    def __init__(self, status: int, body):
        self.status_code = status
        self._raw = body if isinstance(body, bytes) else json.dumps(body).encode()

    def iter_content(self, chunk_size):
        for start in range(0, len(self._raw), chunk_size):
            yield self._raw[start:start + chunk_size]

    def close(self):
        pass


class FakeSession:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests = []
        self.trust_env = True

    def get(self, url, params, timeout, allow_redirects, stream):
        self.requests.append({"url": url, "params": params, "allow_redirects": allow_redirects})
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def client(*responses) -> tuple[SerpApiClient, FakeSession]:
    session = FakeSession(*responses)
    return SerpApiClient(KEY, session=session, retry_delay_s=0), session


OK_BODY = {
    "search_metadata": {"id": "abc", "status": "Success",
                        "json_endpoint": f"https://serpapi.com/searches/abc.json?api_key={KEY}"},
    "search_parameters": {"q": "coat", "api_key": KEY},
    "organic_results": [{"position": 1, "title": "Coat", "link": "https://shop.de/p/1"}],
}


def test_key_is_sent_only_as_param_and_scrubbed_from_body():
    api, session = client(FakeResponse(200, OK_BODY))
    response = api.search({"engine": "google", "q": "coat"})

    sent = session.requests[0]
    assert sent["url"] == "https://serpapi.com/search.json"
    assert sent["params"]["api_key"] == KEY
    assert sent["allow_redirects"] is False
    assert session.trust_env is False
    assert KEY not in json.dumps(response.body)
    assert response.body["search_parameters"]["api_key"] == REDACTED
    assert response.search_id == "abc"
    assert KEY not in repr(api)


def test_key_in_params_is_refused():
    api, _ = client()
    with pytest.raises(ValueError):
        api.search({"q": "coat", "api_key": "other"})


def test_network_error_text_never_contains_the_key():
    leaky = requests.ConnectionError(f"Max retries exceeded with url: /search.json?api_key={KEY}&q=coat")
    api, _ = client(leaky, leaky)
    with pytest.raises(ProviderError) as info:
        api.search({"q": "coat"})
    exc = info.value
    assert KEY not in str(exc) and KEY not in exc.message
    assert exc.__cause__ is None and exc.__suppress_context__
    assert exc.kind == "network"


def test_server_error_is_retried_once():
    api, session = client(FakeResponse(503, {"error": "busy"}), FakeResponse(200, OK_BODY))
    assert api.search({"q": "coat"}).search_id == "abc"
    assert len(session.requests) == 2


def test_search_status_error_is_a_retryable_failure():
    body = {"search_metadata": {"status": "Error"}, "error": "Proxy timeout"}
    api, session = client(FakeResponse(200, body), FakeResponse(200, body))
    with pytest.raises(ProviderError) as info:
        api.search({"q": "coat"})
    assert info.value.kind == "server"
    assert len(session.requests) == 2


@pytest.mark.parametrize(
    "status, error, kind, fatal",
    [
        (401, "Invalid API key.", "auth", True),
        (429, "Your account has run out of searches.", "quota", True),
        (429, "Too many requests this hour.", "throughput", True),
        (400, "Missing query `q` parameter.", "bad_request", False),
    ],
)
def test_error_mapping(status, error, kind, fatal):
    api, session = client(FakeResponse(status, {"error": error}))
    with pytest.raises(ProviderError) as info:
        api.search({"q": "coat"})
    assert (info.value.kind, info.value.fatal, info.value.http_status) == (kind, fatal, status)
    assert len(session.requests) == 1  # not retried


def test_redirect_is_refused():
    api, _ = client(FakeResponse(302, b""))
    with pytest.raises(ProviderError) as info:
        api.search({"q": "coat"})
    assert info.value.kind == "redirect" and info.value.fatal


def test_oversized_response_is_refused():
    session = FakeSession(FakeResponse(200, b"x" * 5000))
    api = SerpApiClient(KEY, session=session, max_bytes=1000, retry_delay_s=0)
    with pytest.raises(ProviderError) as info:
        api.search({"q": "coat"})
    assert info.value.kind == "too_large"


def test_empty_results_are_success_with_message():
    body = {"search_metadata": {"id": "x", "status": "Success"},
            "error": "Google hasn't returned any results for this query."}
    api, _ = client(FakeResponse(200, body))
    response = api.search({"q": "zzzz"})
    assert response.empty_message.startswith("Google hasn't returned")


def test_non_json_body_is_an_error():
    api, _ = client(FakeResponse(200, b"<html>"))
    with pytest.raises(ProviderError) as info:
        api.search({"q": "coat"})
    assert info.value.kind == "invalid_response"


def test_account_keeps_only_quota_fields():
    body = {"api_key": KEY, "account_email": "me@example.com", "plan_name": "Free Plan",
            "searches_per_month": 250, "total_searches_left": 240, "this_hour_searches": 3,
            "account_rate_limit_per_hour": 50}
    api, session = client(FakeResponse(200, body))
    account = api.account()
    assert session.requests[0]["url"] == "https://serpapi.com/account.json"
    assert (account.plan_name, account.searches_left, account.hourly_limit) == ("Free Plan", 240, 50)
    assert "me@example.com" not in repr(account) and KEY not in repr(account)
