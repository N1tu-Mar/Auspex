"""Insert-only persistence for analyses, and reconstruction of the stored contracts.

Everything is written in one transaction: sources, event/market identity (idempotent), snapshots,
then the run and its legs. Nothing is ever updated. Loading rebuilds contracts from rows, so a
content-addressed evidence snapshot that was altered no longer validates.
"""

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app import analysis_models as m
from app.analysis_record import AnalysisRecord
from app.errors import ApiFailure, ErrorCode
from auspex_contracts import (
    AnalysisRun,
    EvidenceSnapshot,
    FeatureSnapshot,
    LegAnalysis,
    Recommendation,
)
from auspex_contracts.analysis import (
    ComboAssessment,
    ExpectedValue,
    InsufficientData,
    LegEstimate,
    RecommendationResult,
    UncertaintyInterval,
)
from auspex_contracts.evidence import EvidenceItem, ProviderFailure, SourceSnapshot
from auspex_contracts.market import Event, Market, MarketSideQuote, MarketSnapshot


def _insert(
    session: Session, model: Any, rows: list[dict[str, Any]], *, ignore: bool = False
) -> None:
    if rows:
        stmt = insert(model).values(rows)
        session.execute(stmt.on_conflict_do_nothing() if ignore else stmt)


def _dump(model: Any) -> Any:
    return None if model is None else model.model_dump(mode="json")


def save(session: Session, record: AnalysisRecord, *, intake_record_id: uuid.UUID) -> None:
    try:
        _save(session, record, intake_record_id)
        session.commit()
    except SQLAlchemyError as exc:
        session.rollback()
        raise ApiFailure(
            503, ErrorCode.PERSISTENCE_FAILED, "Analysis could not be stored; nothing was saved."
        ) from exc


def _save(session: Session, record: AnalysisRecord, intake_record_id: uuid.UUID) -> None:
    run = record.analysis
    sources: dict[SourceSnapshot, uuid.UUID] = {}

    def source_id(source: SourceSnapshot) -> uuid.UUID:
        return sources.setdefault(source, uuid.uuid4())

    for snap in record.market_snapshots:
        source_id(snap.source)
    for evidence in record.evidence_snapshots:
        for item in evidence.items:
            source_id(item.source)
    _insert(
        session,
        m.SourceRecord,
        [{"id": sid, **src.model_dump()} for src, sid in sources.items()],
    )
    _insert(
        session,
        m.EventRecord,
        [
            e.model_dump(exclude={"created_at"}) | {"created_at": e.created_at}
            for e in record.events
        ],
        ignore=True,
    )
    _insert(session, m.MarketRecord, [mk.model_dump() for mk in record.markets], ignore=True)
    _insert(
        session,
        m.MarketSnapshotRecord,
        [
            snap.model_dump(exclude={"source", "sides"})
            | {
                "sides": [s.model_dump(mode="json") for s in snap.sides],
                "warnings": list(snap.warnings),
                "source_id": source_id(snap.source),
            }
            for snap in record.market_snapshots
        ],
    )
    for evidence in record.evidence_snapshots:
        _insert(
            session,
            m.EvidenceItemRecord,
            [
                {
                    "id": item.evidence_id,
                    "event_id": item.event_id,
                    "category": item.category.value,
                    "claim_kind": item.claim_kind.value,
                    "extracted_fact": item.extracted_fact,
                    "excerpt": item.excerpt,
                    "source_id": source_id(item.source),
                    "derived_from": list(item.derived_from),
                }
                for item in evidence.items
            ],
            ignore=True,
        )
        inserted = session.execute(
            insert(m.EvidenceSnapshotRecord)
            .values(
                id=evidence.snapshot_id, event_id=evidence.event_id, created_at=evidence.created_at
            )
            .on_conflict_do_nothing()
            .returning(m.EvidenceSnapshotRecord.id)
        ).all()
        if not inserted:  # identical snapshot already stored; its members and failures are too
            continue
        _insert(
            session,
            m.EvidenceSnapshotItemRecord,
            [
                {
                    "snapshot_id": evidence.snapshot_id,
                    "position": i,
                    "evidence_id": item.evidence_id,
                }
                for i, item in enumerate(evidence.items)
            ],
        )
        _insert(
            session,
            m.ProviderFailureRecord,
            [
                f.model_dump(mode="python")
                | {"id": uuid.uuid4(), "snapshot_id": evidence.snapshot_id}
                for f in evidence.failures
            ],
        )
    _insert(
        session,
        m.FeatureSnapshotRecord,
        [
            fs.model_dump(exclude={"features"})
            | {"features": {k: v.model_dump(mode="json") for k, v in fs.features.items()}}
            for fs in record.feature_snapshots
        ],
    )
    _insert(
        session,
        m.AnalysisRunRecord,
        [
            {
                "id": run.id,
                "created_at": run.created_at,
                "as_of_utc": run.as_of_utc,
                "bet_slip_id": run.bet_slip_id,
                "intake_record_id": intake_record_id,
                "code_version": run.code_version,
                "model_version": run.model_version,
                "recommendation": run.recommendation.recommendation.value,
                "recommendation_reason": run.recommendation.reason,
                "insufficient_reasons": (
                    list(run.recommendation.insufficient_data.reasons)
                    if run.recommendation.insufficient_data
                    else None
                ),
                "combo": _dump(run.combo),
                "expected_value": _dump(run.expected_value),
            }
        ],
    )
    _insert(
        session,
        m.AnalysisLegRecord,
        [
            {
                "analysis_id": run.id,
                "leg_index": leg.leg_index,
                "market_implied_probability": leg.market_implied_probability,
                "consensus_probability": leg.consensus_probability,
                "model_probability": leg.estimate.model_probability if leg.estimate else None,
                "probability_low": leg.estimate.interval.low if leg.estimate else None,
                "probability_high": leg.estimate.interval.high if leg.estimate else None,
                "estimate_model_version": leg.estimate.model_version if leg.estimate else None,
                "estimate_snapshot_captured_at": (
                    leg.estimate.snapshot_captured_at_utc if leg.estimate else None
                ),
                "edge_probability_points": leg.edge_probability_points,
                "insufficient_reasons": (
                    list(leg.insufficient_data.reasons) if leg.insufficient_data else None
                ),
                "event_snapshot_id": leg.event_snapshot_id,
                "market_snapshot_id": leg.market_snapshot_id,
                "evidence_snapshot_id": leg.evidence_snapshot_id,
                "feature_snapshot_id": leg.feature_snapshot_id,
            }
            for leg in run.legs
        ],
    )


def _source(row: m.SourceRecord) -> SourceSnapshot:
    return SourceSnapshot(
        provider=row.provider,
        publisher=row.publisher,
        url=row.url,
        published_at=row.published_at,
        retrieved_at=row.retrieved_at,
        content_sha256=row.content_sha256,
    )


def load(session: Session, analysis_id: uuid.UUID) -> AnalysisRecord | None:
    row = session.get(m.AnalysisRunRecord, analysis_id)
    if row is None:
        return None
    leg_rows = session.scalars(
        select(m.AnalysisLegRecord)
        .where(m.AnalysisLegRecord.analysis_id == analysis_id)
        .order_by(m.AnalysisLegRecord.leg_index)
    ).all()
    legs = tuple(_leg(r) for r in leg_rows)
    reasons = row.insufficient_reasons
    run = AnalysisRun(
        id=row.id,
        created_at=row.created_at,
        as_of_utc=row.as_of_utc,
        bet_slip_id=row.bet_slip_id,
        intake_record_id=row.intake_record_id,
        code_version=row.code_version,
        model_version=row.model_version,
        legs=legs,
        combo=ComboAssessment.model_validate(row.combo) if row.combo else None,
        expected_value=(
            ExpectedValue.model_validate(row.expected_value) if row.expected_value else None
        ),
        recommendation=RecommendationResult(
            recommendation=Recommendation(row.recommendation),
            reason=row.recommendation_reason,
            insufficient_data=InsufficientData(reasons=tuple(reasons)) if reasons else None,
        ),
    )

    market_snaps = tuple(
        _market_snapshot(session, sid)
        for sid in sorted({leg.market_snapshot_id for leg in legs if leg.market_snapshot_id})
    )
    market_keys = {(s.provider, s.market_id) for s in market_snaps}
    markets = tuple(
        Market.model_validate(_columns(mk))
        for key in sorted(market_keys)
        if (mk := session.get(m.MarketRecord, key))
    )
    evidence = tuple(
        _evidence_snapshot(session, eid)
        for eid in sorted({leg.evidence_snapshot_id for leg in legs if leg.evidence_snapshot_id})
    )
    features = tuple(
        _feature_snapshot(session, fid)
        for fid in sorted(
            {leg.feature_snapshot_id for leg in legs if leg.feature_snapshot_id}, key=str
        )
    )
    event_ids = sorted({e.event_id for e in evidence} | {f.event_id for f in features})
    events = tuple(
        Event.model_validate(_columns(ev))
        for eid in event_ids
        if (ev := session.get(m.EventRecord, eid))
    )
    return AnalysisRecord(
        analysis=run,
        events=events,
        markets=markets,
        market_snapshots=market_snaps,
        evidence_snapshots=evidence,
        feature_snapshots=features,
        provider_failures=tuple(f for e in evidence for f in e.failures),
    )


def _columns(row: Any) -> dict[str, Any]:
    return {c.key: getattr(row, c.key) for c in row.__table__.columns}


def _leg(r: m.AnalysisLegRecord) -> LegAnalysis:
    estimate = insufficient = None
    if r.model_probability is not None:
        assert r.probability_low is not None and r.probability_high is not None
        assert r.estimate_model_version and r.estimate_snapshot_captured_at
        estimate = LegEstimate(
            model_probability=r.model_probability,
            interval=UncertaintyInterval(low=r.probability_low, high=r.probability_high),
            model_version=r.estimate_model_version,
            snapshot_captured_at_utc=r.estimate_snapshot_captured_at,
        )
    else:
        insufficient = InsufficientData(reasons=tuple(r.insufficient_reasons or ()))
    return LegAnalysis(
        leg_index=r.leg_index,
        market_implied_probability=r.market_implied_probability,
        consensus_probability=r.consensus_probability,
        estimate=estimate,
        insufficient_data=insufficient,
        edge_probability_points=r.edge_probability_points,
        event_snapshot_id=r.event_snapshot_id,
        market_snapshot_id=r.market_snapshot_id,
        evidence_snapshot_id=r.evidence_snapshot_id,
        feature_snapshot_id=r.feature_snapshot_id,
    )


def _market_snapshot(session: Session, snapshot_id: uuid.UUID) -> MarketSnapshot:
    r = session.get_one(m.MarketSnapshotRecord, snapshot_id)
    source = session.get_one(m.SourceRecord, r.source_id)
    return MarketSnapshot(
        id=r.id,
        provider=r.provider,
        market_id=r.market_id,
        captured_at=r.captured_at,
        title=r.title,
        is_open=r.is_open,
        combo_enabled=r.combo_enabled,
        best_bid_usd=r.best_bid_usd,
        best_ask_usd=r.best_ask_usd,
        fee_coefficient=r.fee_coefficient,
        sides=tuple(MarketSideQuote.model_validate(s) for s in r.sides),
        warnings=tuple(r.warnings),
        source=_source(source),
    )


def _evidence_snapshot(session: Session, snapshot_id: str) -> EvidenceSnapshot:
    snap = session.get_one(m.EvidenceSnapshotRecord, snapshot_id)
    members = session.scalars(
        select(m.EvidenceSnapshotItemRecord)
        .where(m.EvidenceSnapshotItemRecord.snapshot_id == snapshot_id)
        .order_by(m.EvidenceSnapshotItemRecord.position)
    ).all()
    items = []
    for member in members:
        e = session.get_one(m.EvidenceItemRecord, member.evidence_id)
        items.append(
            EvidenceItem(
                evidence_id=e.id,
                event_id=e.event_id,
                category=e.category,
                claim_kind=e.claim_kind,
                extracted_fact=e.extracted_fact,
                excerpt=e.excerpt,
                source=_source(session.get_one(m.SourceRecord, e.source_id)),
                derived_from=tuple(e.derived_from),
            )
        )
    failures = sorted(
        (
            ProviderFailure(
                provider=f.provider,
                kind=f.kind,
                message=f.message,
                occurred_at=f.occurred_at,
            )
            for f in session.scalars(
                select(m.ProviderFailureRecord).where(
                    m.ProviderFailureRecord.snapshot_id == snapshot_id
                )
            )
        ),
        key=failure_order,
    )
    return EvidenceSnapshot(
        snapshot_id=snap.id,
        event_id=snap.event_id,
        created_at=snap.created_at,
        items=tuple(items),
        failures=tuple(failures),
    )


def failure_order(f: ProviderFailure) -> tuple[str, str, str]:
    """Canonical order: the evidence snapshot hash covers failures, and rows have no order."""
    return (f.provider, f.kind.value, f.message)


def _feature_snapshot(session: Session, snapshot_id: uuid.UUID) -> FeatureSnapshot:
    r = session.get_one(m.FeatureSnapshotRecord, snapshot_id)
    return FeatureSnapshot.model_validate(
        {
            "id": r.id,
            "event_id": r.event_id,
            "sport": r.sport,
            "captured_at": r.captured_at,
            "feature_set_version": r.feature_set_version,
            "evidence_snapshot_id": r.evidence_snapshot_id,
            "features": r.features,
        }
    )
