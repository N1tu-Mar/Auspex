"""Validated provider settings from environment variables (prefix `AUSPEX_RESEARCH_`).

The public Polymarket US read endpoints need no credentials, so no secret is read here. A future
keyed provider must add a `SecretStr` field; never a plain `str`, so repr/logs stay masked.
Unknown `AUSPEX_RESEARCH_*` names are rejected so a typo cannot silently fall back to a default.
"""

from collections.abc import Mapping
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from auspex_research.transport import RetryPolicy

ENV_PREFIX = "AUSPEX_RESEARCH_"


class ResearchSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    polymarket_us_base_url: str = "https://gateway.polymarket.us"
    connect_timeout_s: float = Field(default=3.0, gt=0, le=10)
    read_timeout_s: float = Field(default=5.0, gt=0, le=20)
    max_attempts: int = Field(default=3, ge=1, le=5)
    max_concurrency: int = Field(default=4, ge=1, le=16)
    cache_max_entries: int = Field(default=512, ge=1, le=10_000)

    @field_validator("polymarket_us_base_url")
    @classmethod
    def _https_no_credentials(cls, value: str) -> str:
        parts = urlsplit(value)
        if parts.scheme != "https" or not parts.hostname:
            raise ValueError("base url must be an absolute https URL")
        if parts.username or parts.password or parts.query or parts.fragment:
            raise ValueError("base url must not carry credentials, query, or fragment")
        return value.rstrip("/")

    def retry_policy(self) -> RetryPolicy:
        return RetryPolicy(
            timeout_s=self.connect_timeout_s + self.read_timeout_s, max_attempts=self.max_attempts
        )


def load_settings(environ: Mapping[str, str]) -> ResearchSettings:
    """Raises ValueError naming the offending variables (never their values)."""
    values = {
        name.removeprefix(ENV_PREFIX).lower(): value
        for name, value in environ.items()
        if name.startswith(ENV_PREFIX)
    }
    try:
        return ResearchSettings.model_validate(values)
    except ValidationError as exc:
        names = sorted(
            {f"{ENV_PREFIX}{str(e['loc'][0]).upper()}" for e in exc.errors() if e["loc"]}
        )
        raise ValueError(f"invalid research settings: {', '.join(names)}") from exc
