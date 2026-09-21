from enum import StrEnum


class ProviderErrorKind(StrEnum):
    TIMEOUT = "TIMEOUT"
    RATE_LIMITED = "RATE_LIMITED"
    UNAVAILABLE = "UNAVAILABLE"  # network failure or 5xx
    NOT_FOUND = "NOT_FOUND"
    AUTH = "AUTH"  # 401/403: credentials missing, invalid, or not permitted
    BAD_REQUEST = "BAD_REQUEST"  # other 4xx or unfollowed redirect; our request is wrong
    SCHEMA = "SCHEMA"  # response did not match the expected shape
    STALE = "STALE"  # data arrived but is older than the freshness window; dropped, not used


RETRYABLE_KINDS = frozenset(
    {ProviderErrorKind.TIMEOUT, ProviderErrorKind.RATE_LIMITED, ProviderErrorKind.UNAVAILABLE}
)


class ProviderError(Exception):
    """Structured provider failure. Messages must never contain secrets or auth headers."""

    def __init__(
        self,
        kind: ProviderErrorKind,
        provider: str,
        message: str,
        *,
        status_code: int | None = None,
        retry_after_s: float | None = None,
        attempts: int = 1,
    ) -> None:
        super().__init__(f"{provider}: {kind}: {message}")
        self.kind = kind
        self.provider = provider
        self.message = message
        self.status_code = status_code
        self.retry_after_s = retry_after_s
        self.attempts = attempts

    @property
    def retryable(self) -> bool:
        return self.kind in RETRYABLE_KINDS
