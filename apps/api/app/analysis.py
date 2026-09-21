"""POST/GET /api/v1/analyses: research, features, estimate, correlation, recommendation, stored.

Pipeline for one RESOLVED slip: fetch each leg's market and evidence from providers (failures are
kept, never retried here beyond the provider layer's logged, bounded retries), assemble features,
estimate each leg, assess the combo, and apply the recommendation policy. Any missing input is
reported as INSUFFICIENT_DATA with reasons; nothing is defaulted, guessed, or invented.
"""

import uuid
from collections.abc import Callable, Sequence
from dataclasses import asdict
from datetime import datetime, timedelta
from decimal import ROUND_DOWN, Decimal
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import analysis_store
from app.analysis_record import AnalysisRecord, AnalysisRequest
from app.db import IntakeRecord, get_session
from app.errors import ApiError, ApiFailure, ErrorCode
from app.intake import IntakeError, IntakeResult, IntakeState
from app.providers import (
    Estimation,
    get_code_version,
    get_estimation,
    get_evidence_providers,
    get_polymarket,
    utc_now,
)
from auspex_contracts import (
    AnalysisRun,
    BetLeg,
    BetSlip,
    EvidenceSnapshot,
    FeatureSnapshot,
    LegAnalysis,
    Recommendation,
)
from auspex_contracts.analysis import (
    ComboAssessment,
    CorrelationWarning,
    DependencyKind,
    ExpectedValue,
    InsufficientData,
    LegEstimate,
    NaiveIndependentBaseline,
    PositionCosts,
    RecommendationResult,
    UncertaintyInterval,
)
from auspex_contracts.evidence import EvidenceItem, ProviderErrorKind, ProviderFailure
from auspex_contracts.evidence import SourceSnapshot as ContractSource
from auspex_contracts.market import Event, Market, MarketSideQuote, MarketSnapshot
from auspex_prediction import ev as prediction_ev
from auspex_prediction.combo import assess_combo, naive_independent_probability
from auspex_prediction.core import InsufficientData as PredictionInsufficient
from auspex_prediction.correlation import detect_correlation_warnings
from auspex_prediction.policy import recommend
from auspex_research import errors as research_errors
from auspex_research.evidence import EvidenceCategory
from auspex_research.evidence import EvidenceItem as ResearchItem
from auspex_research.evidence import ProviderFailure as ResearchFailure
from auspex_research.providers import (
    EventRef,
    EvidenceProvider,
    NormalizedMarket,
    PolymarketProvider,
    ProviderResponse,
    build_snapshot,
)
from auspex_sports.adapter import FeatureObservation as SportsObservation
from auspex_sports.adapter import FeatureSnapshot as SportsSnapshot
from auspex_sports.adapter import LegEstimate as SportsEstimate
from auspex_sports.adapter import SportAdapter
from auspex_sports.estimator import EstimationContext, estimate_leg
from auspex_sports.mlb import MLB_ADAPTER
from auspex_sports.nfl import NFL_ADAPTER

Clock = Callable[[], datetime]
Result = ProviderResponse[tuple[ResearchItem, ...]] | research_errors.ProviderError

# Explicit freshness windows per evidence category; older evidence is dropped and reported.
# ponytail: fixed defaults, make per-sport if a model needs different windows.
MAX_AGE = {
    EvidenceCategory.MARKET: timedelta(minutes=15),
    EvidenceCategory.ODDS: timedelta(hours=1),
    EvidenceCategory.STATS: timedelta(days=7),
    EvidenceCategory.NEWS: timedelta(hours=24),
    EvidenceCategory.WEATHER: timedelta(hours=6),
    EvidenceCategory.INJURY: timedelta(hours=12),
    EvidenceCategory.LINEUP: timedelta(hours=6),
}
ADAPTERS: dict[str, SportAdapter] = {"NFL": NFL_ADAPTER, "MLB": MLB_ADAPTER}
# No feature extractor exists yet, so snapshots are stored empty and coverage gates abstain.
FEATURE_SET_VERSION = "unassembled-v0"
# The contract's failure kinds predate AUTH and STALE; keep the original kind in the message.
KIND_MAP = {
    research_errors.ProviderErrorKind.AUTH: ProviderErrorKind.BAD_REQUEST,
    research_errors.ProviderErrorKind.STALE: ProviderErrorKind.UNAVAILABLE,
}

router = APIRouter(
    prefix="/api/v1/analyses",
    responses={422: {"model": IntakeError}, 503: {"model": ApiError}},
)


def get_clock() -> Clock:
    return utc_now


def _failure(f: ResearchFailure) -> ProviderFailure:
    mapped = KIND_MAP.get(f.kind)
    return ProviderFailure(
        provider=f.provider,
        kind=mapped or ProviderErrorKind(f.kind.value),
        message=f"[{f.kind.value}] {f.message}" if mapped else f.message,
        occurred_at=f.occurred_at,
    )


def _market_snapshot(market: NormalizedMarket, publisher: str) -> MarketSnapshot:
    return MarketSnapshot(
        provider=market.provider,
        market_id=market.market_id,
        captured_at=market.retrieved_at,
        title=market.title,
        is_open=market.is_open,
        combo_enabled=market.combo_enabled,
        best_bid_usd=market.best_bid_usd,
        best_ask_usd=market.best_ask_usd,
        fee_coefficient=market.fee_coefficient,
        sides=tuple(MarketSideQuote.model_validate(s.model_dump()) for s in market.sides),
        warnings=market.warnings,
        source=ContractSource(
            provider=market.provider,
            publisher=publisher,
            url=market.source_url,
            retrieved_at=market.retrieved_at,
        ),
    )


class Collected:
    """Provider results for one event."""

    def __init__(self, event: Event, evidence: EvidenceSnapshot) -> None:
        self.event, self.evidence = event, evidence
        self.markets: dict[str, tuple[Market, MarketSnapshot]] = {}


async def collect(
    legs: Sequence[BetLeg],
    polymarket: PolymarketProvider,
    evidence_providers: Sequence[EvidenceProvider],
    clock: Clock,
) -> dict[str, Collected]:
    """One evidence snapshot per event, with every provider failure kept inside it."""
    by_event: dict[str, list[BetLeg]] = {}
    for leg in legs:
        assert leg.event_id is not None
        by_event.setdefault(leg.event_id, []).append(leg)
    out: dict[str, Collected] = {}
    for event_id, event_legs in by_event.items():
        first = event_legs[0]
        ref = EventRef(
            event_id=event_id,
            sport=first.sport,
            league=first.league,
            event_start_utc=first.event_start_utc,
            home_participant=first.home_participant,
            away_participant=first.away_participant,
        )
        results: list[
            ProviderResponse[tuple[ResearchItem, ...]] | research_errors.ProviderError
        ] = []
        markets: dict[str, tuple[Market, MarketSnapshot]] = {}
        for market_id in dict.fromkeys(
            leg.polymarket_market_id for leg in event_legs if leg.polymarket_market_id
        ):
            try:
                response = await polymarket.get_market_by_id(market_id)
                snapshot = _market_snapshot(response.data, polymarket.source.publisher)
            except research_errors.ProviderError as exc:
                results.append(exc)
                continue
            except ValidationError:
                results.append(
                    research_errors.ProviderError(
                        research_errors.ProviderErrorKind.SCHEMA,
                        polymarket.source.provider,
                        "market failed contract validation",
                    )
                )
                continue
            market = response.data
            markets[market_id] = (
                Market(
                    provider=market.provider,
                    market_id=market.market_id,
                    event_id=event_id,
                    market_type=market.market_type,
                    provider_market_type=market.provider_market_type,
                    line=market.line,
                    slug=market.slug,
                    created_at=market.retrieved_at,
                ),
                snapshot,
            )
        for provider in evidence_providers:
            try:
                results.append(await provider.fetch_evidence(ref))
            except research_errors.ProviderError as exc:
                results.append(exc)
        created_at = clock()
        raw = build_snapshot(event_id, results, created_at, max_age=MAX_AGE)
        evidence = EvidenceSnapshot(
            event_id=event_id,
            created_at=raw.created_at,
            items=tuple(EvidenceItem.model_validate(i.model_dump()) for i in raw.items),
            failures=tuple(sorted(map(_failure, raw.failures), key=analysis_store.failure_order)),
        )
        collected = Collected(
            Event(event_id=event_id, sport=first.sport, league=first.league, created_at=created_at),
            evidence,
        )
        collected.markets = markets
        out[event_id] = collected
    return out


def assemble_features(
    event: Event, evidence: EvidenceSnapshot, captured_at: datetime
) -> FeatureSnapshot:
    return FeatureSnapshot(
        event_id=event.event_id,
        sport=event.sport,
        captured_at=captured_at,
        feature_set_version=FEATURE_SET_VERSION,
        evidence_snapshot_id=evidence.snapshot_id,
        features={},
    )


def _sports_snapshot(fs: FeatureSnapshot) -> SportsSnapshot:
    return SportsSnapshot(
        captured_at_utc=fs.captured_at,
        features={
            name: SportsObservation(
                value=o.value_decimal if o.value_decimal is not None else o.value_text,
                observed_at_utc=o.observed_at,
                source_ref=o.source_ref,
            )
            for name, o in fs.features.items()
        },
    )


def _market_problems(leg: BetLeg, market: Market, snapshot: MarketSnapshot) -> list[str]:
    problems = []
    if not snapshot.is_open:
        problems.append(f"market {market.market_id} is closed")
    if market.market_type is not None and market.market_type is not leg.market_type:
        problems.append(f"market {market.market_id} is {market.market_type}, not {leg.market_type}")
    if market.line is not None and leg.line is not None and market.line != leg.line:
        problems.append(f"market {market.market_id} line {market.line} differs from {leg.line}")
    return problems


def _contract_warnings(legs: list[BetLeg]) -> list[CorrelationWarning]:
    return [
        CorrelationWarning(
            kind=DependencyKind(w.kind.value),
            leg_indices=w.leg_indices,
            explanation=w.explanation,
        )
        for w in detect_correlation_warnings(legs)
    ]


def analyze(
    slip: BetSlip,
    request: AnalysisRequest,
    collected: dict[str, Collected],
    estimation: Estimation,
    *,
    as_of: datetime,
    created_at: datetime,
    code_version: str,
    bet_slip_id: uuid.UUID,
    intake_record_id: uuid.UUID,
) -> AnalysisRecord:
    features = {
        eid: assemble_features(c.event, c.evidence, created_at) for eid, c in collected.items()
    }
    leg_rows: list[LegAnalysis] = []
    estimates: list[SportsEstimate | None] = []
    problems: list[str] = []
    market_times: list[datetime | None] = []
    for index, leg in enumerate(slip.legs):
        assert leg.event_id is not None
        c = collected[leg.event_id]
        fs = features[leg.event_id]
        market_pair = c.markets.get(leg.polymarket_market_id or "")
        market_snapshot = market_pair[1] if market_pair else None
        market_times.append(market_snapshot.captured_at if market_snapshot else None)
        if market_pair:
            problems += [f"leg {index}: {p}" for p in _market_problems(leg, *market_pair)]
        adapter = ADAPTERS.get(leg.sport.value)
        result: SportsEstimate | PredictionInsufficient
        if adapter is None:
            result = PredictionInsufficient((f"no model coverage for {leg.sport.value}",))
        else:
            result = estimate_leg(
                EstimationContext(adapter, estimation.registry, estimation.predictors),
                leg,
                _sports_snapshot(fs),
                as_of,
            )
        if isinstance(result, PredictionInsufficient):
            estimates.append(None)
            leg_rows.append(
                LegAnalysis(
                    leg_index=index,
                    market_implied_probability=leg.market_price_usd,
                    insufficient_data=InsufficientData(reasons=result.reasons),
                    market_snapshot_id=market_snapshot.id if market_snapshot else None,
                    evidence_snapshot_id=c.evidence.snapshot_id,
                    feature_snapshot_id=fs.id,
                )
            )
            continue
        estimates.append(result)
        leg_rows.append(
            LegAnalysis(
                leg_index=index,
                market_implied_probability=leg.market_price_usd,
                estimate=LegEstimate(
                    model_probability=result.model_probability,
                    interval=UncertaintyInterval(
                        low=result.probability_low,
                        high=result.probability_high,
                    ),
                    model_version=result.model_version,
                    snapshot_captured_at_utc=result.snapshot_captured_at_utc,
                ),
                edge_probability_points=(result.model_probability - leg.market_price_usd) * 100,
                market_snapshot_id=market_snapshot.id if market_snapshot else None,
                evidence_snapshot_id=c.evidence.snapshot_id,
                feature_snapshot_id=fs.id,
            )
        )

    all_estimated = all(e is not None for e in estimates)
    legs = list(slip.legs)
    combo = None
    if len(legs) > 1:
        probs: list[Decimal] = [
            e.model_probability if e is not None else leg.market_price_usd
            for e, leg in zip(estimates, legs, strict=True)
        ]
        joint = assess_combo(legs, probs, as_of_utc=as_of)
        reasons = list(
            joint.reasons
            if isinstance(joint, PredictionInsufficient)
            else joint.joint_probability.reasons
        )
        if not all_estimated:
            reasons.append(
                "baseline uses market-implied probabilities: not every leg has an estimate"
            )
        combo = ComboAssessment(
            naive_baseline=NaiveIndependentBaseline(
                probability=naive_independent_probability(probs).probability
            ),
            warnings=tuple(_contract_warnings(legs)),
            joint_probability=InsufficientData(reasons=tuple(reasons)),
        )
        problems.append("combo: no validated correlation model, so no joint probability")

    ev: ExpectedValue | None = None
    reasons = [
        f"leg {row.leg_index}: {r}"
        for row in leg_rows
        if row.insufficient_data
        for r in row.insufficient_data.reasons
    ] + problems
    decision_reason = ""
    outcome = Recommendation.INSUFFICIENT_DATA
    if not reasons:
        leg, estimate = legs[0], estimates[0]
        assert estimate is not None
        if request.estimated_fees_usd is None or request.estimated_slippage_usd is None:
            reasons.append("fees and slippage were not supplied, so expected value is unknown")
        else:
            costs = prediction_ev.PositionCosts(
                stake_usd=slip.stake_usd,
                gross_payout_usd=slip.gross_payout_usd or _implied_payout(slip.stake_usd, leg),
                estimated_fees_usd=request.estimated_fees_usd,
                estimated_slippage_usd=request.estimated_slippage_usd,
            )
            value = prediction_ev.evaluate_position(estimate.model_probability, costs)
            ev = ExpectedValue(
                costs=PositionCosts.model_validate(asdict(costs)),
                **asdict(value),
            )
            decision = recommend(
                estimate, value, market_times[0], as_of, detect_correlation_warnings(legs)
            )
            outcome, decision_reason = decision.recommendation, "; ".join(decision.reasons)
            if outcome is Recommendation.INSUFFICIENT_DATA:
                reasons = list(decision.reasons)
    if reasons:
        outcome = Recommendation.INSUFFICIENT_DATA
        decision_reason = "; ".join(reasons)
    recommendation = RecommendationResult(
        recommendation=outcome,
        reason=decision_reason,
        insufficient_data=(
            InsufficientData(reasons=tuple(reasons))
            if outcome is Recommendation.INSUFFICIENT_DATA
            else None
        ),
    )
    versions = sorted({e.model_version for e in estimates if e is not None})
    run = AnalysisRun(
        created_at=created_at,
        as_of_utc=as_of,
        bet_slip_id=bet_slip_id,
        intake_record_id=intake_record_id,
        code_version=code_version,
        model_version=",".join(versions) or "none",
        legs=tuple(leg_rows),
        combo=combo,
        expected_value=ev,
        recommendation=recommendation,
    )
    evidence = tuple(c.evidence for c in collected.values())
    return AnalysisRecord(
        analysis=run,
        events=tuple(c.event for c in collected.values()),
        markets=tuple(mk for c in collected.values() for mk, _ in c.markets.values()),
        market_snapshots=tuple(s for c in collected.values() for _, s in c.markets.values()),
        evidence_snapshots=evidence,
        feature_snapshots=tuple(features.values()),
        provider_failures=tuple(f for e in evidence for f in e.failures),
    )


Db = Annotated[Session, Depends(get_session)]


def _implied_payout(stake: Decimal, leg: BetLeg) -> Decimal:
    """Payout of the stake at the leg price, rounded down to cents (the contract's precision)."""
    exact = prediction_ev.gross_payout_usd_for_shares(stake, leg.market_price_usd)
    return exact.quantize(Decimal("0.01"), rounding=ROUND_DOWN)


def _intake_for(session: Session, request: AnalysisRequest) -> IntakeRecord:
    if request.intake_trace_id is not None:
        record = session.get(IntakeRecord, request.intake_trace_id)
    else:
        record = session.scalars(
            select(IntakeRecord)
            .where(IntakeRecord.bet_slip_id == request.bet_slip_id)
            .order_by(IntakeRecord.received_at.desc())
            .limit(1)
        ).first()
    if record is None:
        raise ApiFailure(404, ErrorCode.NOT_FOUND, "No stored intake record for that id.")
    return record


@router.post("", status_code=201, responses={404: {"model": ApiError}, 409: {"model": ApiError}})
async def create_analysis(
    request: AnalysisRequest,
    session: Db,
    clock: Annotated[Clock, Depends(get_clock)],
    polymarket: Annotated[PolymarketProvider, Depends(get_polymarket)],
    evidence_providers: Annotated[Sequence[EvidenceProvider], Depends(get_evidence_providers)],
    estimation: Annotated[Estimation, Depends(get_estimation)],
    code_version: Annotated[str, Depends(get_code_version)],
) -> AnalysisRecord:
    """Analyze a RESOLVED stored slip and persist an immutable analysis record."""
    record = _intake_for(session, request)
    intake = IntakeResult.model_validate(record.result)
    if (
        intake.state is not IntakeState.RESOLVED
        or intake.slip is None
        or intake.bet_slip_id is None
    ):
        raise ApiFailure(
            409,
            ErrorCode.INTAKE_NOT_RESOLVED,
            f"Intake {record.id} is {intake.state}; resolve it and resubmit before analysis.",
        )
    as_of = clock()
    collected = await collect(intake.slip.legs, polymarket, evidence_providers, clock)
    result = analyze(
        intake.slip,
        request,
        collected,
        estimation,
        as_of=as_of,
        created_at=clock(),
        code_version=code_version,
        bet_slip_id=intake.bet_slip_id,
        intake_record_id=record.id,
    )
    analysis_store.save(session, result, intake_record_id=record.id)
    stored = analysis_store.load(session, result.analysis.id)
    assert stored is not None
    return stored


@router.get("/{analysis_id}", responses={404: {"model": ApiError}})
def get_analysis(analysis_id: uuid.UUID, session: Db) -> AnalysisRecord:
    """A stored analysis exactly as saved, with every snapshot it cites."""
    stored = analysis_store.load(session, analysis_id)
    if stored is None:
        raise ApiFailure(404, ErrorCode.NOT_FOUND, f"No analysis {analysis_id}.")
    return stored
