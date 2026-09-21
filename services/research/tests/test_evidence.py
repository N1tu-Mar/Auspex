from datetime import UTC, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from auspex_research.errors import ProviderErrorKind
from auspex_research.evidence import (
    ClaimKind,
    EvidenceCategory,
    EvidenceItem,
    EvidenceSnapshot,
    ProviderFailure,
    SourceSnapshot,
)

RETRIEVED = datetime(2026, 9, 20, 16, 0, tzinfo=UTC)


def source(**overrides: object) -> SourceSnapshot:
    fields: dict[str, object] = {
        "provider": "fixture_news",
        "publisher": "Example Team Site",
        "url": "https://example.com/news/qb-update",
        "published_at": datetime(2026, 9, 20, 11, 0, tzinfo=timezone(timedelta(hours=-4))),
        "retrieved_at": RETRIEVED,
    }
    return SourceSnapshot.model_validate(fields | overrides)


def item(**overrides: object) -> EvidenceItem:
    fields: dict[str, object] = {
        "event_id": "evt-1",
        "category": EvidenceCategory.INJURY,
        "claim_kind": ClaimKind.CONFIRMED_FACT,
        "extracted_fact": "Starting QB listed as questionable (ankle).",
        "excerpt": "is listed as questionable with an ankle injury",
        "source": source(),
    }
    return EvidenceItem.model_validate(fields | overrides)


def test_source_preserves_metadata_and_normalizes_to_utc() -> None:
    s = source()
    assert s.published_at == datetime(2026, 9, 20, 15, 0, tzinfo=UTC)
    assert s.published_at.tzinfo is UTC
    assert source(published_at=None).published_at is None  # publication time is optional


@pytest.mark.parametrize(
    "overrides",
    [
        {"url": "ftp://example.com/x"},
        {"url": "/relative/path"},
        {"retrieved_at": datetime(2026, 9, 20, 16, 0)},  # naive timestamp  # noqa: DTZ001
        {"published_at": RETRIEVED + timedelta(minutes=1)},  # published after retrieval
        {"content_sha256": "not-a-hash"},
    ],
)
def test_source_rejects_invalid(overrides: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        source(**overrides)


def test_every_claim_kind_is_distinct() -> None:
    assert {k.value for k in ClaimKind} == {
        "CONFIRMED_FACT",
        "PROJECTION",
        "RUMOR",
        "OPINION",
        "INFERENCE",
    }


def test_inference_must_cite_evidence_and_others_must_not() -> None:
    fact = item()
    inference = item(
        claim_kind=ClaimKind.INFERENCE,
        extracted_fact="QB snap share likely reduced.",
        excerpt=None,
        derived_from=(fact.evidence_id,),
    )
    assert inference.derived_from == (fact.evidence_id,)
    with pytest.raises(ValidationError, match="must cite"):
        item(claim_kind=ClaimKind.INFERENCE)
    with pytest.raises(ValidationError, match="only an INFERENCE"):
        item(claim_kind=ClaimKind.RUMOR, derived_from=(fact.evidence_id,))


def test_excerpt_is_short() -> None:
    with pytest.raises(ValidationError):
        item(excerpt="x" * 301)


def test_item_is_immutable_and_content_addressed() -> None:
    a = item()
    assert len(a.evidence_id) == 64
    assert item().evidence_id == a.evidence_id  # deterministic
    assert item(claim_kind=ClaimKind.RUMOR).evidence_id != a.evidence_id
    with pytest.raises(ValidationError):
        a.extracted_fact = "changed"  # type: ignore[misc]
    # Round trip through storage re-verifies the id.
    assert EvidenceItem.model_validate_json(a.model_dump_json()) == a
    tampered = a.model_dump() | {"extracted_fact": "Starting QB ruled out."}
    with pytest.raises(ValidationError, match="does not match content"):
        EvidenceItem.model_validate(tampered)


def snapshot(**overrides: object) -> EvidenceSnapshot:
    fields: dict[str, object] = {
        "event_id": "evt-1",
        "created_at": RETRIEVED + timedelta(seconds=5),
        "items": (item(),),
    }
    return EvidenceSnapshot.model_validate(fields | overrides)


def test_snapshot_keeps_partial_failures_visible() -> None:
    failure = ProviderFailure(
        provider="fixture_weather",
        kind=ProviderErrorKind.TIMEOUT,
        message="timed out after 3 attempts",
        occurred_at=RETRIEVED,
    )
    snap = snapshot(failures=(failure,))
    assert snap.items and snap.failures == (failure,)
    assert EvidenceSnapshot.model_validate_json(snap.model_dump_json()) == snap
    assert snap.snapshot_id != snapshot().snapshot_id


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"items": (item(), item())}, "duplicate"),
        ({"event_id": "evt-2"}, "belongs to event"),
        ({"created_at": RETRIEVED - timedelta(seconds=1)}, "retrieved after"),
        (
            {"items": (item(claim_kind=ClaimKind.INFERENCE, derived_from=("0" * 64,)),)},
            "not in snapshot",
        ),
    ],
)
def test_snapshot_rejects_inconsistent_evidence(overrides: dict[str, object], message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        snapshot(**overrides)
