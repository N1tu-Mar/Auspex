import asyncio
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime

import pytest

from auspex_research.errors import ProviderError, ProviderErrorKind
from auspex_research.fixtures import FixtureTransport
from auspex_research.providers import SourceIdentity
from auspex_research.transport import (
    Fetcher,
    Outcome,
    RawResponse,
    RequestEvent,
    RetryPolicy,
    build_url,
    redact_url,
)

SOURCE = SourceIdentity("p", "P", "https://api.test")
NOW = datetime(2026, 9, 21, 12, 0, tzinfo=UTC)
URL = "https://api.test/v1/x"


def fetch(
    routes: list[RawResponse], events: list[RequestEvent], sleeps: list[float] | None = None
) -> Fetcher:
    async def sleep(delay: float) -> None:
        if sleeps is not None:
            sleeps.append(delay)

    return Fetcher(
        FixtureTransport({URL: routes}),
        RetryPolicy(),
        on_event=events.append,
        clock=lambda: NOW,
        sleep=sleep,
        jitter=lambda: 1.0,
    )


def test_redaction_masks_credentials_userinfo_and_fragments() -> None:
    url = "https://user:pw@api.test/v1/x?slug=a&API_KEY=s3cret&access_token=t&sig=z#frag"
    shown = redact_url(url)
    assert (
        shown == "https://api.test/v1/x?slug=a&API_KEY=REDACTED&access_token=REDACTED&sig=REDACTED"
    )
    assert "s3cret" not in shown and "pw" not in shown


def test_build_url_is_deterministic_and_encodes_values() -> None:
    a = build_url(SOURCE, "/v1/x", {"z": 1, "a": True, "m": "x y"})
    assert a == build_url(SOURCE, "/v1/x", {"m": "x y", "a": True, "z": 1})
    assert a == "https://api.test/v1/x?a=true&m=x+y&z=1"


def test_retry_then_ok_emits_structured_events() -> None:
    events: list[RequestEvent] = []
    asyncio.run(
        fetch([RawResponse(503, b""), RawResponse(200, b"{}")], events).get(SOURCE, "/v1/x")
    )
    assert [(e.attempt, e.outcome, e.status_code, e.kind) for e in events] == [
        (1, Outcome.RETRY, 503, ProviderErrorKind.UNAVAILABLE),
        (2, Outcome.OK, None, None),
    ]
    assert events[0].retry_delay_s == pytest.approx(0.25) and events[0].elapsed_ms >= 0
    assert all(e.provider == "p" and e.url == URL for e in events)


def test_final_failure_is_marked_failed() -> None:
    events: list[RequestEvent] = []
    with pytest.raises(ProviderError):
        asyncio.run(fetch([RawResponse(404, b"")], events).get(SOURCE, "/v1/x"))
    assert [(e.outcome, e.kind) for e in events] == [(Outcome.FAILED, ProviderErrorKind.NOT_FOUND)]


def test_logged_url_is_redacted_but_request_is_not() -> None:
    events: list[RequestEvent] = []
    transport = FixtureTransport({URL + "?token=s3cret": RawResponse(200, b"{}")})
    f = Fetcher(transport, on_event=events.append, clock=lambda: NOW)
    response = asyncio.run(f.get(SOURCE, "/v1/x", {"token": "s3cret"}))
    assert transport.calls == [URL + "?token=s3cret"]
    assert events[0].url == response.url == URL + "?token=REDACTED"


def test_retry_after_http_date_is_honoured() -> None:
    sleeps: list[float] = []
    when = format_datetime(NOW + timedelta(seconds=7), usegmt=True)
    routes = [RawResponse(429, b"", {"retry-after": when}), RawResponse(200, b"{}")]
    asyncio.run(fetch(routes, [], sleeps).get(SOURCE, "/v1/x"))
    assert sleeps == [7.0]


def test_retry_after_on_503_is_honoured_and_junk_falls_back_to_jitter() -> None:
    sleeps: list[float] = []
    routes = [
        RawResponse(503, b"", {"retry-after": "3"}),
        RawResponse(503, b"", {"retry-after": "soon"}),
        RawResponse(200, b"{}"),
    ]
    asyncio.run(fetch(routes, [], sleeps).get(SOURCE, "/v1/x"))
    assert sleeps == [3.0, 0.5]  # second: jitter 1.0 * base 0.25 * 2


def test_past_retry_after_date_does_not_sleep_negative() -> None:
    sleeps: list[float] = []
    when = format_datetime(NOW - timedelta(hours=1), usegmt=True)
    routes = [RawResponse(429, b"", {"retry-after": when}), RawResponse(200, b"{}")]
    asyncio.run(fetch(routes, [], sleeps).get(SOURCE, "/v1/x"))
    assert sleeps == [0.0]


def test_limiter_bounds_concurrent_requests() -> None:
    active = peak = 0

    async def transport(url: str) -> RawResponse:
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        active -= 1
        return RawResponse(200, b"{}")

    async def go() -> None:
        f = Fetcher(transport, limiter=asyncio.Semaphore(2), clock=lambda: NOW)
        await asyncio.gather(*(f.get(SOURCE, "/v1/x") for _ in range(6)))

    asyncio.run(go())
    assert peak == 2
