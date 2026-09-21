"""In-memory TTL cache for decoded provider responses.

Key = provider id + full request URL (query params sorted by the fetcher), so different
providers, paths, or filters never share an entry. Only successful responses are stored. An
expired entry is evicted on read and reported as a miss: stale data is never returned, and a
failed refresh surfaces as an error rather than falling back to old data. A hit keeps its original
`retrieved_at`, so provenance and age stay honest.
"""

import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import replace
from typing import Any

from auspex_research.providers import ProviderResponse, SourceIdentity


def cache_key(source: SourceIdentity, url: str) -> str:
    return f"{source.provider}|{url}"


class TTLCache:
    """Bounded (least-recently-stored evicted first), single-event-loop safe."""

    def __init__(self, max_entries: int = 512, now: Callable[[], float] = time.monotonic) -> None:
        if max_entries < 1:
            raise ValueError("max_entries must be positive")
        self._max = max_entries
        self._now = now
        self._entries: OrderedDict[str, tuple[float, ProviderResponse[Any]]] = OrderedDict()

    def __len__(self) -> int:
        return len(self._entries)

    async def get(self, key: str) -> ProviderResponse[Any] | None:
        entry = self._entries.get(key)
        if entry is None:
            return None
        expires_at, response = entry
        if self._now() >= expires_at:
            del self._entries[key]
            return None
        return replace(response, from_cache=True, attempts=0)

    async def set(self, key: str, response: ProviderResponse[Any], ttl_seconds: float) -> None:
        if ttl_seconds <= 0:
            return  # ttl 0 disables caching
        self._entries.pop(key, None)
        self._entries[key] = (self._now() + ttl_seconds, response)
        while len(self._entries) > self._max:
            self._entries.popitem(last=False)
