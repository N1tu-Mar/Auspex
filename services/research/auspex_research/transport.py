"""Read-only HTTP boundary: strict timeout, bounded retries with full jitter, 429 handling.

The transport itself is a Protocol so tests and fixtures never touch the network. There is no
method argument: every request is a GET, so no adapter can write to a provider. `Fetcher` adds the
retry policy, TTL cache, bounded concurrency, and redacted structured diagnostics on top.
"""

import asyncio
import json
import logging
import random
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from enum import StrEnum
from typing import Any, Protocol
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from auspex_research.cache import cache_key
from auspex_research.errors import ProviderError, ProviderErrorKind
from auspex_research.providers import ProviderResponse, ResponseCache, SourceIdentity

Param = str | int | bool
_SENSITIVE = ("key", "token", "secret", "sig", "auth", "pass", "cred")
logger = logging.getLogger("auspex_research")


@dataclass(frozen=True)
class RawResponse:
    status_code: int
    body: bytes
    headers: Mapping[str, str] = field(default_factory=dict)  # lower-case names


class Transport(Protocol):
    """Performs one GET. Raises OSError (or TimeoutError) on network failure."""

    async def __call__(self, url: str) -> RawResponse: ...


@dataclass(frozen=True)
class RetryPolicy:
    timeout_s: float = 8.0  # per attempt, whole request (connect + read); backs the httpx timeouts
    max_attempts: int = 3
    base_delay_s: float = 0.25
    max_delay_s: float = 4.0
    max_retry_after_s: float = 30.0  # a longer server-requested wait fails fast instead
    max_body_bytes: int = 2_000_000

    def __post_init__(self) -> None:
        if not (1 <= self.max_attempts <= 5 and 0 < self.timeout_s <= 30):
            raise ValueError("retry policy must stay bounded")


class Outcome(StrEnum):
    OK = "OK"
    CACHE_HIT = "CACHE_HIT"
    RETRY = "RETRY"  # attempt failed, another follows
    FAILED = "FAILED"  # attempt failed, giving up


@dataclass(frozen=True)
class RequestEvent:
    """One structured diagnostic. URL is redacted; no headers or bodies are ever included."""

    provider: str
    url: str
    attempt: int
    outcome: Outcome
    elapsed_ms: float
    status_code: int | None = None
    kind: ProviderErrorKind | None = None
    retry_delay_s: float | None = None


def log_event(event: RequestEvent) -> None:
    """Default sink: one structured INFO record per request event."""
    logger.info("provider_request", extra={"provider_request": asdict(event)})


def utc_now() -> datetime:
    return datetime.now(UTC)


def redact_url(url: str) -> str:
    """Drop userinfo and mask credential-looking query values before a URL is logged or stored."""
    parts = urlsplit(url)
    host = parts.netloc.rpartition("@")[2]
    query = urlencode(
        [
            (k, "REDACTED" if any(s in k.lower() for s in _SENSITIVE) else v)
            for k, v in parse_qsl(parts.query, keep_blank_values=True)
        ]
    )
    return urlunsplit((parts.scheme, host, parts.path, query, ""))


def build_url(source: SourceIdentity, path: str, params: Mapping[str, Param] | None) -> str:
    """Deterministic URL: sorted params so the same request always has the same cache key."""
    url = source.base_url.rstrip("/") + path
    if not params:
        return url
    pairs = sorted(
        (k, str(v).lower() if isinstance(v, bool) else str(v)) for k, v in params.items()
    )
    return f"{url}?{urlencode(pairs)}"


def _retry_after(headers: Mapping[str, str], now: datetime) -> float | None:
    value = headers.get("retry-after", "").strip()
    try:
        return max(0.0, float(value))
    except ValueError:
        pass
    try:
        when = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None  # garbage: fall back to jittered backoff
    return max(0.0, (when - now).total_seconds()) if when.tzinfo else None


def _error_for_status(raw: RawResponse, provider: str, now: datetime) -> ProviderError:
    status = raw.status_code
    retry_after = None
    if status == 429:
        kind = ProviderErrorKind.RATE_LIMITED
    elif status == 503:
        kind = ProviderErrorKind.UNAVAILABLE
    elif status == 404:
        kind = ProviderErrorKind.NOT_FOUND
    elif status in {401, 403}:
        kind = ProviderErrorKind.AUTH
    elif status < 500:  # unfollowed 3xx and other 4xx
        kind = ProviderErrorKind.BAD_REQUEST
    else:
        kind = ProviderErrorKind.UNAVAILABLE
    if status in {429, 503}:
        retry_after = _retry_after(raw.headers, now)
    return ProviderError(
        kind, provider, f"HTTP {status}", status_code=status, retry_after_s=retry_after
    )


@dataclass(frozen=True)
class Fetcher:
    """GET + JSON-decode with retry, optional cache, and diagnostics. Callers schema-validate."""

    transport: Transport
    policy: RetryPolicy = RetryPolicy()
    cache: ResponseCache | None = None
    on_event: Callable[[RequestEvent], None] | None = None
    limiter: asyncio.Semaphore | None = None  # bounds concurrent in-flight requests
    clock: Callable[[], datetime] = utc_now
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep
    jitter: Callable[[], float] = random.random

    def _emit(self, event: RequestEvent) -> None:
        if self.on_event is not None:
            self.on_event(event)

    async def _once(self, url: str, provider: str) -> Any:
        try:
            async with asyncio.timeout(self.policy.timeout_s):
                raw = await self.transport(url)
        except TimeoutError as exc:
            raise ProviderError(
                ProviderErrorKind.TIMEOUT, provider, f"no response in {self.policy.timeout_s}s"
            ) from exc
        except OSError as exc:
            raise ProviderError(
                ProviderErrorKind.UNAVAILABLE, provider, type(exc).__name__
            ) from exc
        if not 200 <= raw.status_code < 300:
            raise _error_for_status(raw, provider, self.clock())
        if len(raw.body) > self.policy.max_body_bytes:
            raise ProviderError(
                ProviderErrorKind.SCHEMA,
                provider,
                "response body too large",
                status_code=raw.status_code,
            )
        try:
            return json.loads(raw.body)
        except ValueError as exc:
            raise ProviderError(
                ProviderErrorKind.SCHEMA,
                provider,
                "response is not JSON",
                status_code=raw.status_code,
            ) from exc

    async def _attempt(self, url: str, provider: str) -> Any:
        if self.limiter is None:
            return await self._once(url, provider)
        async with self.limiter:
            return await self._once(url, provider)

    async def get(
        self,
        source: SourceIdentity,
        path: str,
        params: Mapping[str, Param] | None = None,
        *,
        ttl_seconds: float = 0.0,
    ) -> ProviderResponse[Any]:
        url = build_url(source, path, params)
        shown = redact_url(url)
        key = cache_key(source, url)
        if self.cache is not None and ttl_seconds > 0 and (hit := await self.cache.get(key)):
            self._emit(RequestEvent(source.provider, shown, 0, Outcome.CACHE_HIT, 0.0))
            return hit
        policy = self.policy
        for attempt in range(1, policy.max_attempts + 1):
            started = time.perf_counter()
            try:
                data = await self._attempt(url, source.provider)
            except ProviderError as exc:
                exc.attempts = attempt
                delay = self._backoff(exc, attempt)
                final = delay is None
                self._emit(
                    RequestEvent(
                        source.provider,
                        shown,
                        attempt,
                        Outcome.FAILED if final else Outcome.RETRY,
                        (time.perf_counter() - started) * 1000,
                        exc.status_code,
                        exc.kind,
                        delay,
                    )
                )
                if delay is None:
                    raise
                await self.sleep(delay)
            else:
                self._emit(
                    RequestEvent(
                        source.provider,
                        shown,
                        attempt,
                        Outcome.OK,
                        (time.perf_counter() - started) * 1000,
                    )
                )
                response = ProviderResponse(
                    source=source, url=shown, retrieved_at=self.clock(), data=data, attempts=attempt
                )
                if self.cache is not None and ttl_seconds > 0:
                    await self.cache.set(key, response, ttl_seconds)
                return response
        raise AssertionError("unreachable")  # pragma: no cover

    def _backoff(self, exc: ProviderError, attempt: int) -> float | None:
        """Seconds to wait before retrying, or None to give up."""
        policy = self.policy
        if not exc.retryable or attempt == policy.max_attempts:
            return None
        if exc.retry_after_s is not None:
            return exc.retry_after_s if exc.retry_after_s <= policy.max_retry_after_s else None
        return self.jitter() * min(policy.max_delay_s, policy.base_delay_s * 2.0 ** (attempt - 1))


async def fetch_json(
    transport: Transport,
    source: SourceIdentity,
    path: str,
    policy: RetryPolicy = RetryPolicy(),  # noqa: B008 - frozen, safe to share
    *,
    clock: Callable[[], datetime] = utc_now,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    jitter: Callable[[], float] = random.random,
) -> ProviderResponse[Any]:
    """Uncached one-shot GET; use Fetcher directly for cache, limiter, or diagnostics."""
    return await Fetcher(transport, policy, clock=clock, sleep=sleep, jitter=jitter).get(
        source, path
    )
