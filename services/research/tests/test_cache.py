import asyncio
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

import pytest

from auspex_research.cache import TTLCache, cache_key
from auspex_research.fixtures import FixtureTransport
from auspex_research.providers import ProviderResponse, SourceIdentity
from auspex_research.transport import Fetcher, RawResponse, RetryPolicy

SOURCE = SourceIdentity("p", "P", "https://api.test")
OTHER = SourceIdentity("q", "Q", "https://api.test")
NOW = datetime(2026, 9, 21, 12, 0, tzinfo=UTC)


class Clock:
    t = 0.0

    def __call__(self) -> float:
        return self.t


def response(data: Any = 1) -> ProviderResponse[Any]:
    return ProviderResponse(SOURCE, "https://api.test/x", NOW, data)


def test_hit_before_expiry_then_miss_and_eviction_after() -> None:
    clock = Clock()
    cache = TTLCache(now=clock)

    async def go() -> None:
        await cache.set("k", response(), 10)
        hit = await cache.get("k")
        assert hit is not None and hit.from_cache and hit.attempts == 0
        assert hit.retrieved_at == NOW  # provenance keeps the original retrieval time
        clock.t = 9.99
        assert await cache.get("k") is not None
        clock.t = 10.0  # expiry is inclusive: never serve at or past TTL
        assert await cache.get("k") is None
        assert len(cache) == 0

    asyncio.run(go())


def test_zero_ttl_never_stores_and_capacity_is_bounded() -> None:
    cache = TTLCache(max_entries=2, now=Clock())

    async def go() -> None:
        await cache.set("zero", response(), 0)
        assert len(cache) == 0
        for key in "abc":
            await cache.set(key, response(key), 10)
        assert await cache.get("a") is None and await cache.get("c") is not None

    asyncio.run(go())
    with pytest.raises(ValueError, match="positive"):
        TTLCache(max_entries=0)


def test_key_separates_providers_and_query_strings() -> None:
    url = "https://api.test/v1/e?a=1"
    assert len({cache_key(SOURCE, url), cache_key(OTHER, url), cache_key(SOURCE, url + "2")}) == 3


def test_fetcher_serves_within_ttl_and_never_stale_after() -> None:
    clock = Clock()
    url = "https://api.test/v1/thing"
    transport = FixtureTransport(
        {url: [RawResponse(200, b'{"v": 1}'), RawResponse(200, b'{"v": 2}')]}
    )
    fetcher = Fetcher(transport, RetryPolicy(), TTLCache(now=clock), clock=lambda: NOW)

    async def go() -> list[ProviderResponse[Any]]:
        out = [await fetcher.get(SOURCE, "/v1/thing", ttl_seconds=5)]
        clock.t = 4
        out.append(await fetcher.get(SOURCE, "/v1/thing", ttl_seconds=5))
        clock.t = 5
        out.append(await fetcher.get(SOURCE, "/v1/thing", ttl_seconds=5))
        return out

    first, cached, refreshed = asyncio.run(go())
    assert (first.data, cached.data, refreshed.data) == ({"v": 1}, {"v": 1}, {"v": 2})
    assert (first.from_cache, cached.from_cache, refreshed.from_cache) == (False, True, False)
    assert len(transport.calls) == 2


def test_failed_refresh_raises_instead_of_reusing_expired_data() -> None:
    clock = Clock()
    url = "https://api.test/v1/thing"
    transport = FixtureTransport({url: [RawResponse(200, b"{}"), RawResponse(500, b"")]})
    fetcher = Fetcher(
        transport, RetryPolicy(max_attempts=1), TTLCache(now=clock), clock=lambda: NOW
    )

    async def go() -> None:
        await fetcher.get(SOURCE, "/v1/thing", ttl_seconds=5)
        clock.t = 6
        await fetcher.get(SOURCE, "/v1/thing", ttl_seconds=5)

    with pytest.raises(Exception, match="HTTP 500"):
        asyncio.run(go())


def test_errors_and_ttl_zero_are_not_cached() -> None:
    url = "https://api.test/v1/thing"
    transport = FixtureTransport({url: [RawResponse(404, b""), RawResponse(200, b"{}")]})
    cache = TTLCache(now=Clock())
    fetcher = Fetcher(transport, RetryPolicy(max_attempts=1), cache, clock=lambda: NOW)

    async def go() -> None:
        with pytest.raises(Exception, match="HTTP 404"):
            await fetcher.get(SOURCE, "/v1/thing", ttl_seconds=5)
        assert len(cache) == 0
        await fetcher.get(SOURCE, "/v1/thing", ttl_seconds=0)
        assert len(cache) == 0

    asyncio.run(go())
    assert replace(response(), from_cache=True).from_cache
