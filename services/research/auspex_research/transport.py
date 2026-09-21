"""Read-only HTTP boundary: strict timeout, bounded retries with full jitter, 429 handling.

The transport itself is a Protocol so tests and fixtures never touch the network. There is no
method argument: every request is a GET, so no adapter can write to a provider.
"""

import asyncio
import json
import random
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol

from auspex_research.errors import ProviderError, ProviderErrorKind
from auspex_research.providers import ProviderResponse, SourceIdentity


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
    timeout_s: float = 5.0  # per attempt
    max_attempts: int = 3
    base_delay_s: float = 0.25
    max_delay_s: float = 4.0
    max_retry_after_s: float = 30.0  # a longer server-requested wait fails fast instead
    max_body_bytes: int = 2_000_000

    def __post_init__(self) -> None:
        if not (1 <= self.max_attempts <= 5 and 0 < self.timeout_s <= 30):
            raise ValueError("retry policy must stay bounded")


def utc_now() -> datetime:
    return datetime.now(UTC)


def _retry_after(headers: Mapping[str, str]) -> float | None:
    try:
        return max(0.0, float(headers.get("retry-after", "")))
    except ValueError:
        return None  # HTTP-date form or garbage: fall back to jittered backoff


def _error_for_status(raw: RawResponse, provider: str) -> ProviderError:
    status = raw.status_code
    if status == 429:
        kind = ProviderErrorKind.RATE_LIMITED
    elif status == 404:
        kind = ProviderErrorKind.NOT_FOUND
    elif 400 <= status < 500:
        kind = ProviderErrorKind.BAD_REQUEST
    else:
        kind = ProviderErrorKind.UNAVAILABLE
    return ProviderError(
        kind,
        provider,
        f"HTTP {status}",
        status_code=status,
        retry_after_s=_retry_after(raw.headers) if status == 429 else None,
    )


async def _attempt(transport: Transport, url: str, source: str, policy: RetryPolicy) -> Any:
    try:
        async with asyncio.timeout(policy.timeout_s):
            raw = await transport(url)
    except TimeoutError as exc:
        raise ProviderError(
            ProviderErrorKind.TIMEOUT, source, f"no response in {policy.timeout_s}s"
        ) from exc
    except OSError as exc:
        raise ProviderError(ProviderErrorKind.UNAVAILABLE, source, type(exc).__name__) from exc
    if not 200 <= raw.status_code < 300:
        raise _error_for_status(raw, source)
    if len(raw.body) > policy.max_body_bytes:
        raise ProviderError(ProviderErrorKind.SCHEMA, source, "response body too large")
    try:
        return json.loads(raw.body)
    except ValueError as exc:
        raise ProviderError(ProviderErrorKind.SCHEMA, source, "response is not JSON") from exc


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
    """GET base_url + path and decode JSON. Callers still schema-validate the payload."""
    url = source.base_url.rstrip("/") + path
    for attempt in range(1, policy.max_attempts + 1):
        try:
            data = await _attempt(transport, url, source.provider, policy)
        except ProviderError as exc:
            exc.attempts = attempt
            if not exc.retryable or attempt == policy.max_attempts:
                raise
            if exc.retry_after_s is not None:
                if exc.retry_after_s > policy.max_retry_after_s:
                    raise
                delay = exc.retry_after_s
            else:
                cap = min(policy.max_delay_s, policy.base_delay_s * 2 ** (attempt - 1))
                delay = jitter() * cap  # full jitter
            await sleep(delay)
        else:
            return ProviderResponse(
                source=source, url=url, retrieved_at=clock(), data=data, attempts=attempt
            )
    raise AssertionError("unreachable")  # pragma: no cover
