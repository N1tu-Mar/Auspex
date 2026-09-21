"""Live `Transport` over httpx. Tests use `httpx.MockTransport`; nothing here needs a network.

Read-only by construction (GET only, redirects not followed, no request body). Connect/read/write
timeouts are set on the client; `Fetcher` still bounds the whole attempt. httpx errors are mapped
to TimeoutError/OSError carrying only the exception type, so URLs and headers never reach messages.
"""

from types import TracebackType
from typing import Self

import httpx

from auspex_research.settings import ResearchSettings
from auspex_research.transport import RawResponse

USER_AGENT = "auspex-research/0.1 (read-only)"


class HttpxTransport:
    def __init__(self, client: httpx.AsyncClient, max_body_bytes: int) -> None:
        self._client = client
        self._limit = max_body_bytes

    @classmethod
    def from_settings(cls, settings: ResearchSettings, max_body_bytes: int = 2_000_000) -> Self:
        timeout = httpx.Timeout(
            connect=settings.connect_timeout_s,
            read=settings.read_timeout_s,
            write=settings.read_timeout_s,
            pool=settings.connect_timeout_s,
        )
        limits = httpx.Limits(max_connections=settings.max_concurrency)
        client = httpx.AsyncClient(
            timeout=timeout,
            limits=limits,
            follow_redirects=False,
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        )
        return cls(client, max_body_bytes)

    async def __call__(self, url: str) -> RawResponse:
        try:
            async with self._client.stream("GET", url) as response:
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    body += chunk
                    if len(body) > self._limit:  # stop early; Fetcher rejects the oversize body
                        break
                headers = {k.lower(): v for k, v in response.headers.items()}
                return RawResponse(response.status_code, bytes(body), headers)
        except httpx.TimeoutException as exc:
            raise TimeoutError(type(exc).__name__) from None
        except httpx.HTTPError as exc:
            raise OSError(type(exc).__name__) from None

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()
