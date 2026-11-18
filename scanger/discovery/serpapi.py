"""SerpApi adapter for M04: the only place that knows how SerpApi is called.

SerpApi takes the API key as a URL query parameter, so the request URL is a
secret. Nothing here logs, stores or returns that URL, and network exceptions
(whose text contains it) are replaced by fixed messages with no chained cause.
Response bodies are scrubbed of the key before anyone else sees them.

Only https://serpapi.com is contacted. Redirects are refused, response size is
capped, and environment proxies/.netrc are ignored.
"""

import json
import time
from dataclasses import dataclass
from typing import Any

import requests

from scanger.leads import clean_text

SEARCH_URL = "https://serpapi.com/search.json"
ACCOUNT_URL = "https://serpapi.com/account.json"
# Route name used in Scanger -> SerpApi engine.
ENGINES = {"organic": "google", "shopping": "google_shopping"}
REDACTED = "[REDACTED]"
MAX_RESPONSE_BYTES = 8 * 1024 * 1024
TIMEOUT = (5, 60)  # connect, read (seconds)
RETRY_DELAY_S = 2.0


class ProviderError(Exception):
    """A SerpApi request failed. `message` never contains the API key.

    `fatal` means later calls in the same run would fail the same way
    (bad key, no searches left, hourly limit), so the run should stop.
    """

    def __init__(self, kind: str, message: str, http_status: int | None = None,
                 retryable: bool = False, fatal: bool = False):
        super().__init__(message)
        self.kind = kind
        self.message = message
        self.http_status = http_status
        self.retryable = retryable
        self.fatal = fatal


@dataclass(frozen=True)
class ProviderResponse:
    http_status: int
    body: dict[str, Any]  # redacted
    search_id: str | None
    search_status: str | None
    # SerpApi reports "no results" as a successful search with an `error` text.
    empty_message: str | None
    duration_s: float


@dataclass(frozen=True)
class AccountStatus:
    plan_name: str | None
    searches_per_month: int | None
    searches_left: int | None
    this_hour_searches: int | None
    hourly_limit: int | None


def redact(value: Any, secret: str) -> Any:
    """Return `value` with every occurrence of `secret` and any api_key field replaced."""
    if isinstance(value, dict):
        return {k: (REDACTED if k == "api_key" else redact(v, secret)) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v, secret) for v in value]
    if isinstance(value, str) and secret and secret in value:
        return value.replace(secret, REDACTED)
    return value


class SerpApiClient:
    name = "serpapi"

    def __init__(self, api_key: str, session: requests.Session | None = None,
                 timeout: tuple[float, float] = TIMEOUT, max_bytes: int = MAX_RESPONSE_BYTES,
                 retry_delay_s: float = RETRY_DELAY_S):
        if not api_key or not api_key.strip():
            raise ValueError("A SerpApi key is required.")
        self._api_key = api_key.strip()
        self._session = session or requests.Session()
        self._session.trust_env = False
        self.timeout = timeout
        self.max_bytes = max_bytes
        self.retry_delay_s = retry_delay_s

    def __repr__(self) -> str:
        return "SerpApiClient(api_key=[REDACTED])"

    # --- public -------------------------------------------------------------

    def search(self, params: dict[str, str]) -> ProviderResponse:
        """Run one search. Retries once on timeouts, network errors and 5xx.

        A retry with identical parameters is normally served from SerpApi's
        one-hour cache, which is free, if the first attempt did complete there.
        """
        if "api_key" in params:
            raise ValueError("Pass the key to the client, not in params.")
        try:
            return self._search_once(params)
        except ProviderError as exc:
            if not exc.retryable:
                raise
        time.sleep(self.retry_delay_s)
        return self._search_once(params)

    def account(self) -> AccountStatus:
        """Read quota from the free Account API. Its body also contains the key
        and the account e-mail, so only the quota fields are kept."""
        status, body = self._get(ACCOUNT_URL, {})
        if status != 200:
            raise _error_for(status, body)

        def number(key: str) -> int | None:
            value = body.get(key)
            return value if isinstance(value, int) else None

        plan = body.get("plan_name")
        return AccountStatus(
            plan_name=plan if isinstance(plan, str) else None,
            searches_per_month=number("searches_per_month"),
            searches_left=number("total_searches_left"),
            this_hour_searches=number("this_hour_searches"),
            hourly_limit=number("account_rate_limit_per_hour"),
        )

    # --- internals ----------------------------------------------------------

    def _search_once(self, params: dict[str, str]) -> ProviderResponse:
        started = time.monotonic()
        status, body = self._get(SEARCH_URL, params)
        duration = time.monotonic() - started
        metadata = body.get("search_metadata") if isinstance(body.get("search_metadata"), dict) else {}
        search_status = metadata.get("status") if isinstance(metadata.get("status"), str) else None
        error = body.get("error") if isinstance(body.get("error"), str) else None
        if status != 200 or search_status == "Error":
            raise _error_for(status, body)
        search_id = metadata.get("id") if isinstance(metadata.get("id"), str) else None
        return ProviderResponse(
            http_status=status,
            body=body,
            search_id=search_id,
            search_status=search_status,
            empty_message=error,
            duration_s=duration,
        )

    def _get(self, url: str, params: dict[str, str]) -> tuple[int, dict[str, Any]]:
        query = {**params, "api_key": self._api_key}
        try:
            response = self._session.get(
                url, params=query, timeout=self.timeout, allow_redirects=False, stream=True
            )
        except requests.Timeout:
            raise ProviderError(
                "timeout", f"SerpApi did not answer within {self.timeout[1]:.0f}s.", retryable=True
            ) from None
        except requests.RequestException as exc:
            # str(exc) would contain the request URL, including the key.
            raise ProviderError(
                "network", f"Could not reach SerpApi ({type(exc).__name__}).", retryable=True
            ) from None
        try:
            if 300 <= response.status_code < 400:
                raise ProviderError(
                    "redirect", f"SerpApi answered with a redirect ({response.status_code}); refused.",
                    http_status=response.status_code, fatal=True,
                )
            raw = self._read_capped(response)
        finally:
            response.close()
        try:
            body = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            if response.status_code >= 500:
                raise ProviderError(
                    "server", f"SerpApi server error {response.status_code}.",
                    http_status=response.status_code, retryable=True,
                ) from None
            raise ProviderError(
                "invalid_response", f"SerpApi returned a non-JSON response ({response.status_code}).",
                http_status=response.status_code,
            ) from None
        if not isinstance(body, dict):
            raise ProviderError("invalid_response", "SerpApi returned JSON that is not an object.",
                                http_status=response.status_code)
        return response.status_code, redact(body, self._api_key)

    def _read_capped(self, response: requests.Response) -> bytes:
        chunks, size = [], 0
        try:
            for chunk in response.iter_content(chunk_size=65536):
                size += len(chunk)
                if size > self.max_bytes:
                    raise ProviderError(
                        "too_large", f"SerpApi response exceeded {self.max_bytes} bytes; refused.",
                        http_status=response.status_code,
                    )
                chunks.append(chunk)
        except requests.RequestException:
            raise ProviderError(
                "network", "Connection to SerpApi failed while reading the response.", retryable=True
            ) from None
        return b"".join(chunks)


def _error_for(status: int, body: dict[str, Any]) -> ProviderError:
    detail = clean_text(body.get("error"), 300) or ""
    if status == 401:
        return ProviderError("auth", "SerpApi rejected the API key (401). Check SERPAPI_API_KEY.",
                             http_status=status, fatal=True)
    if status == 403:
        return ProviderError("forbidden", f"SerpApi refused the request (403). {detail}".strip(),
                             http_status=status, fatal=True)
    if status == 429:
        kind = "quota" if "run out of searches" in detail.lower() else "throughput"
        return ProviderError(kind, f"SerpApi limit reached (429): {detail or 'too many requests'}",
                             http_status=status, fatal=True)
    if status == 400:
        return ProviderError("bad_request", f"SerpApi rejected the parameters (400): {detail}",
                             http_status=status)
    if status >= 500 or status == 200:
        # 200 here means search_metadata.status == "Error" (e.g. proxy timeout).
        return ProviderError("server", f"SerpApi could not complete the search ({status}): {detail}",
                             http_status=status, retryable=True)
    return ProviderError("http", f"SerpApi returned HTTP {status}: {detail}", http_status=status)
