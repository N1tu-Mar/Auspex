"""API shapes for analyses. Everything inside is an `auspex_contracts` type."""

import uuid
from decimal import Decimal
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from auspex_contracts import AnalysisRun, EvidenceSnapshot, FeatureSnapshot
from auspex_contracts.evidence import ProviderFailure
from auspex_contracts.market import Event, Market, MarketSnapshot

Usd = Annotated[Decimal, Field(ge=0)]


class AnalysisRequest(BaseModel):
    """Analyze a stored, RESOLVED slip. Give exactly one of the two ids."""

    model_config = ConfigDict(extra="forbid")

    intake_trace_id: uuid.UUID | None = None
    bet_slip_id: uuid.UUID | None = None
    estimated_fees_usd: Usd | None = Field(
        default=None, description="Caller-supplied; fees are never assumed."
    )
    estimated_slippage_usd: Usd | None = Field(
        default=None, description="Caller-supplied; slippage is never assumed."
    )

    @model_validator(mode="after")
    def _one_id(self) -> Self:
        if (self.intake_trace_id is None) == (self.bet_slip_id is None):
            raise ValueError("set exactly one of intake_trace_id or bet_slip_id")
        return self


class AnalysisRecord(BaseModel):
    """A stored analysis with every snapshot it cites, as persisted (POST and GET are identical)."""

    model_config = ConfigDict(extra="forbid")

    analysis: AnalysisRun
    events: tuple[Event, ...]
    markets: tuple[Market, ...]
    market_snapshots: tuple[MarketSnapshot, ...]
    evidence_snapshots: tuple[EvidenceSnapshot, ...]
    feature_snapshots: tuple[FeatureSnapshot, ...]
    provider_failures: tuple[ProviderFailure, ...] = Field(
        description="Every failed or stale provider call from all evidence snapshots."
    )
