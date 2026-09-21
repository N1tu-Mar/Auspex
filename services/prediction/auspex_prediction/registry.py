"""Versioned model registry: metadata only, no model code.

A model is ACTIVE only with an evaluation artifact for exactly that model and code version that
beats a baseline on an adequate sample. Nothing else can produce an ACTIVE record.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Protocol

from auspex_contracts import MarketType, Sport
from auspex_prediction.core import require_aware
from auspex_prediction.evaluation import EvaluationArtifact


class ModelStatus(StrEnum):
    REGISTERED = "REGISTERED"  # known, unevaluated; never used for estimates
    SHADOW = "SHADOW"  # may run offline for evaluation; never used for estimates
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


@dataclass(frozen=True)
class TrainingProvenance:
    dataset_ref: str
    trained_at_utc: datetime
    training_window: str  # human-readable data window, e.g. "2018-09..2024-02"

    def __post_init__(self) -> None:
        if not (self.dataset_ref and self.training_window):
            raise ValueError("dataset_ref and training_window are required")
        require_aware("trained_at_utc", self.trained_at_utc)


@dataclass(frozen=True)
class ModelMetadata:
    model_id: str
    version: str
    code_version: str  # git SHA or package version of the code that produced the model
    sport: Sport
    leagues: frozenset[str]
    market_types: frozenset[MarketType]
    max_interval_width: Decimal  # model-specific abstention limit
    training: TrainingProvenance
    status: ModelStatus = ModelStatus.REGISTERED
    evaluation: EvaluationArtifact | None = None

    def __post_init__(self) -> None:
        for name in ("model_id", "version", "code_version"):
            if not getattr(self, name):
                raise ValueError(f"{name} is required")
        if not self.leagues or not self.market_types:
            raise ValueError("coverage rules need at least one league and one market type")
        if self.status is ModelStatus.ACTIVE:
            ev = self.evaluation
            if ev is None:
                raise ValueError("ACTIVE model requires an evaluation artifact")
            if (ev.model_version, ev.code_version) != (self.version, self.code_version):
                raise ValueError("evaluation artifact does not match model and code version")
            if not ev.supports_activation:
                raise ValueError("evaluation does not beat baseline on an adequate sample")


class ModelRegistry(Protocol):
    def register(self, model: ModelMetadata) -> None: ...

    def get(self, model_id: str, version: str) -> ModelMetadata | None: ...

    def active_for(
        self, sport: Sport, league: str, market_type: MarketType
    ) -> ModelMetadata | None: ...


class InMemoryModelRegistry:
    def __init__(self, models: Iterable[ModelMetadata] = ()) -> None:
        self._models: dict[tuple[str, str], ModelMetadata] = {}
        for m in models:
            self.register(m)

    def register(self, model: ModelMetadata) -> None:
        key = (model.model_id, model.version)
        if key in self._models:
            raise ValueError(f"model {key} already registered; versions are immutable")
        if model.status is ModelStatus.ACTIVE:
            for league in model.leagues:
                for market in model.market_types:
                    if self.active_for(model.sport, league, market) is not None:
                        raise ValueError(f"an active model already covers {league} {market.value}")
        self._models[key] = model

    def get(self, model_id: str, version: str) -> ModelMetadata | None:
        return self._models.get((model_id, version))

    def active_for(
        self, sport: Sport, league: str, market_type: MarketType
    ) -> ModelMetadata | None:
        for m in self._models.values():
            if (
                m.status is ModelStatus.ACTIVE
                and m.sport is sport
                and league in m.leagues
                and market_type in m.market_types
            ):
                return m
        return None
