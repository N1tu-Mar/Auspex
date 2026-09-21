"""Production wiring for provider-backed retrieval. Tests override these dependencies."""

import logging
import os
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path

from auspex_prediction.registry import InMemoryModelRegistry, ModelRegistry
from auspex_research.cache import TTLCache
from auspex_research.httpx_transport import HttpxTransport
from auspex_research.polymarket import PolymarketUSClient
from auspex_research.providers import EvidenceProvider, PolymarketProvider
from auspex_research.settings import load_settings
from auspex_research.transport import Fetcher, RequestEvent
from auspex_sports.estimator import Predictor, PredictorKey

log = logging.getLogger("auspex.providers")


def _log_request(event: RequestEvent) -> None:
    # Every attempt is visible; the Fetcher's retries are bounded and never silent.
    log.info("provider request %s", event)


@lru_cache
def get_polymarket() -> PolymarketProvider:
    settings = load_settings(os.environ)
    fetcher = Fetcher(
        HttpxTransport.from_settings(settings),
        settings.retry_policy(),
        cache=TTLCache(settings.cache_max_entries),
        on_event=_log_request,
    )
    return PolymarketUSClient(fetcher)


def get_evidence_providers() -> Sequence[EvidenceProvider]:
    # Stats, news, weather, injury, and lineup providers are Protocols only; none is implemented.
    return ()


def utc_now() -> datetime:
    return datetime.now(UTC)


@lru_cache
def get_code_version() -> str:
    """Git commit of the running code (`AUSPEX_CODE_VERSION` overrides, e.g. in a container)."""
    if configured := os.environ.get("AUSPEX_CODE_VERSION"):
        return configured
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],  # noqa: S607
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
            cwd=Path(__file__).parent,
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    return out.stdout.strip() or "unknown"


@dataclass(frozen=True)
class Estimation:
    registry: ModelRegistry
    predictors: Mapping[PredictorKey, Predictor]


def get_estimation() -> Estimation:
    # No model has an evaluation artifact yet, so nothing can be ACTIVE and every leg abstains.
    return Estimation(InMemoryModelRegistry(), {})
