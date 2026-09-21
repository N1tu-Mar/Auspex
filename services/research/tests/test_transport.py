import asyncio
from datetime import UTC, datetime, timedelta, timezone
from typing import Any, Final

import pytest

from auspex_contracts import Sport
from auspex_research.errors import ProviderError, ProviderErrorKind
from auspex_research.evidence import ClaimKind, EvidenceCategory, EvidenceItem, SourceSnapshot
from auspex_research.fixtures import FixtureTransport
from auspex_research.providers import (
    CachePolicy,
    EventRef,
    NewsProvider,
    ProviderResponse,
    SourceIdentity,
    build_snapshot,
)
from auspex_research.transport import RawResponse, RetryPolicy, Transport, fetch_json

SOURCE = SourceIdentity(provider="fixture", publisher="Fixture", base_url="https://api.test")
URL = "https://api.test/v1/thing"
NOW = datetime(2026, 9, 21, 12, 0, tzinfo=UTC)
OK = RawResponse(200, b'{"ok": true}')


def run(
    transport: Transport,
    policy: RetryPolicy = RetryPolicy(),  # noqa: B008
    sleeps: list[float] | None = None,
) -> ProviderResponse[Any]:
    async def sleep(delay: float) -> None:
        if sleeps is not None:
            sleeps.append(delay)

    return asyncio.run(
        fetch_json(
            transport,
            SOURCE,
            "/v1/thing",
            policy,
            clock=lambda: NOW,
            sleep=sleep,
            jitter=lambda: 0.5,
        )
    )


def test_success_records_source_url_and_timestamp() -> None:
    response = run(FixtureTransport({URL: OK}))
    assert response.data == {"ok": True}
    assert (response.source, response.url, response.retrieved_at) == (SOURCE, URL, NOW)
    assert response.attempts == 1 and not response.from_cache


def test_retries_5xx_with_bounded_full_jitter() -> None:
    sleeps: list[float] = []
    transport = FixtureTransport({URL: [RawResponse(503, b""), RawResponse(502, b""), OK]})
    response = run(transport, sleeps=sleeps)
    assert response.attempts == 3 and len(transport.calls) == 3
    assert sleeps == [0.5 * 0.25, 0.5 * 0.5]  # jitter * min(max_delay, base * 2**n)


def test_gives_up_after_max_attempts() -> None:
    transport = FixtureTransport({URL: RawResponse(500, b"")})
    with pytest.raises(ProviderError) as err:
        run(transport, RetryPolicy(max_attempts=2))
    assert err.value.kind is ProviderErrorKind.UNAVAILABLE
    assert err.value.attempts == 2 and len(transport.calls) == 2


def test_rate_limit_honours_retry_after() -> None:
    sleeps: list[float] = []
    limited = RawResponse(429, b"", {"retry-after": "2"})
    response = run(FixtureTransport({URL: [limited, OK]}), sleeps=sleeps)
    assert response.attempts == 2 and sleeps == [2.0]


def test_rate_limit_with_excessive_retry_after_fails_fast() -> None:
    transport = FixtureTransport({URL: RawResponse(429, b"", {"retry-after": "600"})})
    with pytest.raises(ProviderError) as err:
        run(transport)
    assert err.value.kind is ProviderErrorKind.RATE_LIMITED
    assert err.value.retry_after_s == 600 and len(transport.calls) == 1


@pytest.mark.parametrize(
    ("response", "kind"),
    [
        (RawResponse(404, b""), ProviderErrorKind.NOT_FOUND),
        (RawResponse(403, b""), ProviderErrorKind.BAD_REQUEST),
        (RawResponse(200, b"<html>"), ProviderErrorKind.SCHEMA),
        (RawResponse(200, b"[" + b"1," * 1_000_000 + b"1]"), ProviderErrorKind.SCHEMA),
    ],
)
def test_non_retryable_failures_are_structured(
    response: RawResponse, kind: ProviderErrorKind
) -> None:
    transport = FixtureTransport({URL: response})
    with pytest.raises(ProviderError) as err:
        run(transport)
    assert err.value.kind is kind and not err.value.retryable
    assert len(transport.calls) == 1


def test_timeout_is_strict_and_retried() -> None:
    calls = 0

    async def slow(url: str) -> RawResponse:
        nonlocal calls
        calls += 1
        await asyncio.sleep(1)
        return OK

    with pytest.raises(ProviderError) as err:
        run(slow, RetryPolicy(timeout_s=0.01, max_attempts=2))
    assert err.value.kind is ProviderErrorKind.TIMEOUT and calls == 2


def test_network_error_is_unavailable() -> None:
    async def down(url: str) -> RawResponse:
        raise ConnectionRefusedError

    with pytest.raises(ProviderError) as err:
        run(down, RetryPolicy(max_attempts=1))
    assert err.value.kind is ProviderErrorKind.UNAVAILABLE


def test_retry_policy_must_be_bounded() -> None:
    with pytest.raises(ValueError, match="bounded"):
        RetryPolicy(max_attempts=50)
    with pytest.raises(ValueError, match="bounded"):
        RetryPolicy(timeout_s=0)


def test_cache_policy_freshness() -> None:
    policy = CachePolicy(ttl_seconds=30)
    assert policy.is_fresh(NOW, NOW + timedelta(seconds=29))
    assert not policy.is_fresh(NOW, NOW + timedelta(seconds=30))
    assert not CachePolicy(ttl_seconds=0).is_fresh(NOW, NOW)


def test_build_snapshot_keeps_evidence_when_a_provider_fails() -> None:
    evidence = EvidenceItem(
        event_id="evt-1",
        category=EvidenceCategory.WEATHER,
        claim_kind=ClaimKind.PROJECTION,
        extracted_fact="Forecast: 18 mph wind at kickoff.",
        source=SourceSnapshot(provider="fixture", publisher="Fixture", url=URL, retrieved_at=NOW),
    )
    ok = ProviderResponse(source=SOURCE, url=URL, retrieved_at=NOW, data=(evidence, evidence))
    failed = ProviderError(ProviderErrorKind.TIMEOUT, "fixture_news", "no response in 5.0s")
    snap = build_snapshot("evt-1", [ok, failed], NOW)
    assert snap.items == (evidence,)  # duplicate report collapsed
    assert [(f.provider, f.kind) for f in snap.failures] == [
        ("fixture_news", ProviderErrorKind.TIMEOUT)
    ]


class FixtureNewsProvider:
    source = SOURCE
    cache_policy = CachePolicy(ttl_seconds=300)
    category: Final = EvidenceCategory.NEWS

    def __init__(self, items: tuple[EvidenceItem, ...]) -> None:
        self.items = items

    async def fetch_evidence(self, event: EventRef) -> ProviderResponse[tuple[EvidenceItem, ...]]:
        return ProviderResponse(source=SOURCE, url=URL, retrieved_at=NOW, data=self.items)


def test_evidence_providers_are_distinguished_by_category() -> None:
    news: NewsProvider = FixtureNewsProvider(())  # mypy rejects this for any other category
    event = EventRef(
        event_id="evt-1",
        sport=Sport.NFL,
        league="NFL",
        event_start_utc=datetime(2026, 9, 27, 16, 25, tzinfo=timezone(timedelta(hours=-4))),
    )
    assert event.event_start_utc == datetime(2026, 9, 27, 20, 25, tzinfo=UTC)
    assert asyncio.run(news.fetch_evidence(event)).data == ()
    assert news.category is EvidenceCategory.NEWS
