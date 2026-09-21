"""Authoritative Auspex domain contracts.

These Pydantic models are the single source of truth for cross-language types.
TypeScript types are generated from the API OpenAPI schema; never hand-write them.
"""

from auspex_contracts.analysis import (
    AnalysisRef,
    AnalysisRun,
    ComboAssessment,
    CorrelationWarning,
    DependencyKind,
    ExpectedValue,
    InsufficientData,
    LegAnalysis,
    LegEstimate,
    NaiveIndependentBaseline,
    PositionCosts,
    RecommendationResult,
    UncertaintyInterval,
)
from auspex_contracts.bet_slip import (
    BetLeg,
    BetSlip,
    LegStatus,
    MarketType,
    Recommendation,
    Side,
    Sport,
)
from auspex_contracts.evidence import (
    ClaimKind,
    EvidenceCategory,
    EvidenceItem,
    EvidenceSnapshot,
    ProviderErrorKind,
    ProviderFailure,
    SourceSnapshot,
)
from auspex_contracts.features import FeatureObservation, FeatureSnapshot
from auspex_contracts.market import (
    Event,
    EventSnapshot,
    Market,
    MarketSideQuote,
    MarketSnapshot,
)

__all__ = [
    "AnalysisRef",
    "AnalysisRun",
    "BetLeg",
    "BetSlip",
    "ClaimKind",
    "ComboAssessment",
    "CorrelationWarning",
    "DependencyKind",
    "Event",
    "EventSnapshot",
    "EvidenceCategory",
    "EvidenceItem",
    "EvidenceSnapshot",
    "ExpectedValue",
    "FeatureObservation",
    "FeatureSnapshot",
    "InsufficientData",
    "LegAnalysis",
    "LegEstimate",
    "LegStatus",
    "Market",
    "MarketSideQuote",
    "MarketSnapshot",
    "MarketType",
    "NaiveIndependentBaseline",
    "PositionCosts",
    "ProviderErrorKind",
    "ProviderFailure",
    "Recommendation",
    "RecommendationResult",
    "Side",
    "SourceSnapshot",
    "Sport",
    "UncertaintyInterval",
]
