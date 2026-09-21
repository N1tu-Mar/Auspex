import asyncio
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest

from auspex_research.errors import ProviderError, ProviderErrorKind
from auspex_research.httpx_transport import USER_AGENT, HttpxTransport
from auspex_research.providers import ProviderResponse, SourceIdentity
from auspex_research.settings import ResearchSettings
from auspex_research.transport import Fetcher, RetryPolicy

SOURCE = SourceIdentity("p", "P", "https://api.test")
NOW = datetime(2026, 9, 21, 12, 0, tzinfo=UTC)


def fetcher(handler: httpx.MockTransport, limit: int = 2_000_000) -> Fetcher:
    client = httpx.AsyncClient(transport=handler, follow_redirects=False)
    policy = RetryPolicy(max_attempts=2, base_delay_s=0.0, max_body_bytes=limit)

    async def no_sleep(_: float) -> None:
        return None

    return Fetcher(HttpxTransport(client, limit), policy, clock=lambda: NOW, sleep=no_sleep)


def get(f: Fetcher) -> ProviderResponse[Any]:
    return asyncio.run(f.get(SOURCE, "/v1/x", {"slug": "a b"}))


def test_get_only_json_headers_and_sorted_params() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"ok": True})

    response = asyncio.run(
        fetcher(httpx.MockTransport(handler)).get(SOURCE, "/v1/x", {"b": 1, "a": True})
    )
    assert response.data == {"ok": True}
    (request,) = seen
    assert request.method == "GET" and request.content == b""
    assert str(request.url) == "https://api.test/v1/x?a=true&b=1"
    assert "authorization" not in request.headers


@pytest.mark.parametrize(
    ("exc", "kind"),
    [
        (httpx.ConnectTimeout("secret-token in text"), ProviderErrorKind.TIMEOUT),
        (httpx.ReadTimeout("t"), ProviderErrorKind.TIMEOUT),
        (httpx.ConnectError("secret-token in text"), ProviderErrorKind.UNAVAILABLE),
        (httpx.RemoteProtocolError("p"), ProviderErrorKind.UNAVAILABLE),
    ],
)
def test_httpx_errors_map_to_typed_failures_without_leaking_text(
    exc: Exception, kind: ProviderErrorKind
) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise exc

    with pytest.raises(ProviderError) as err:
        get(fetcher(httpx.MockTransport(handler)))
    assert err.value.kind is kind and err.value.attempts == 2 == calls  # retried once
    assert "secret-token" not in str(err.value)


def test_redirects_are_not_followed() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "https://evil.test/"})

    with pytest.raises(ProviderError) as err:
        get(fetcher(httpx.MockTransport(handler)))
    assert err.value.kind is ProviderErrorKind.BAD_REQUEST and err.value.attempts == 1


def test_oversize_body_is_cut_off_and_rejected() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"[" + b"1," * 5000 + b"1]")

    with pytest.raises(ProviderError) as err:
        get(fetcher(httpx.MockTransport(handler), limit=1000))
    assert err.value.kind is ProviderErrorKind.SCHEMA


def test_retry_after_header_reaches_the_retry_policy() -> None:
    replies = iter([httpx.Response(429, headers={"Retry-After": "2"}), httpx.Response(200, json=1)])
    slept: list[float] = []

    async def sleep(delay: float) -> None:
        slept.append(delay)

    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: next(replies)))
    f = Fetcher(HttpxTransport(client, 1000), RetryPolicy(), clock=lambda: NOW, sleep=sleep)
    assert asyncio.run(f.get(SOURCE, "/v1/x")).data == 1
    assert slept == [2.0]


def test_from_settings_sets_strict_timeouts_and_no_redirects() -> None:
    settings = ResearchSettings(connect_timeout_s=1.5, read_timeout_s=2.5, max_concurrency=3)

    async def go() -> httpx.AsyncClient:
        async with HttpxTransport.from_settings(settings) as transport:
            return transport._client

    client = asyncio.run(go())
    assert (client.timeout.connect, client.timeout.read) == (1.5, 2.5)
    assert not client.follow_redirects and client.headers["user-agent"] == USER_AGENT
    assert client.is_closed
