from datetime import UTC, datetime, timedelta

import pytest

from auspex_research.errors import ProviderError, ProviderErrorKind
from auspex_research.evidence import (
    ClaimKind,
    EvidenceCategory,
    EvidenceItem,
    EvidenceSnapshot,
    SourceSnapshot,
)
from auspex_research.providers import ProviderResponse, SourceIdentity, build_snapshot

NOW = datetime(2026, 9, 21, 12, 0, tzinfo=UTC)
SRC = SourceIdentity("news_a", "A", "https://a.test")
SRC_B = SourceIdentity("news_b", "B", "https://b.test")
AGE = {c: timedelta(hours=24) for c in EvidenceCategory}


def item(
    fact: str = "Starting QB is questionable.",
    *,
    provider: str = "news_a",
    age: timedelta = timedelta(hours=1),
    kind: ClaimKind = ClaimKind.RUMOR,
    category: EvidenceCategory = EvidenceCategory.NEWS,
    derived_from: tuple[str, ...] = (),
    published: bool = False,
) -> EvidenceItem:
    when = NOW - age
    return EvidenceItem(
        event_id="evt-1",
        category=category,
        claim_kind=kind,
        extracted_fact=fact,
        derived_from=derived_from,
        source=SourceSnapshot(
            provider=provider,
            publisher=provider,
            url=f"https://{provider}.test/x",
            published_at=when if published else None,
            retrieved_at=NOW - timedelta(minutes=1) if published else when,
        ),
    )


def ok(
    src: SourceIdentity, *items: EvidenceItem, cached: bool = False
) -> ProviderResponse[tuple[EvidenceItem, ...]]:
    return ProviderResponse(
        src,
        f"{src.base_url}/q?api_key=REDACTED",
        NOW,
        items,
        from_cache=cached,
        attempts=0 if cached else 1,
    )


def build(*results: ProviderResponse[tuple[EvidenceItem, ...]] | ProviderError) -> EvidenceSnapshot:
    return build_snapshot("evt-1", results, NOW, max_age=AGE)


def test_partial_failure_keeps_good_evidence_failures_and_provenance() -> None:
    snap = build(
        ok(SRC, item()),
        ProviderError(ProviderErrorKind.RATE_LIMITED, "weather", "HTTP 429"),
        ok(SRC_B),  # succeeded with nothing: provenance still recorded
    )
    assert len(snap.items) == 1
    assert [(f.provider, f.kind) for f in snap.failures] == [
        ("weather", ProviderErrorKind.RATE_LIMITED)
    ]
    assert [(r.provider, r.item_count) for r in snap.runs] == [("news_a", 1), ("news_b", 0)]
    assert EvidenceSnapshot.model_validate_json(snap.model_dump_json()) == snap


def test_cache_provenance_is_recorded() -> None:
    (run,) = build(ok(SRC, item(), cached=True)).runs
    assert run.from_cache and run.attempts == 0 and "REDACTED" in run.url


def test_stale_evidence_is_dropped_and_reported_never_used() -> None:
    snap = build(ok(SRC, item("old news", age=timedelta(hours=25)), item("fresh news")))
    assert [i.extracted_fact for i in snap.items] == ["fresh news"]
    (failure,) = snap.failures
    assert failure.kind is ProviderErrorKind.STALE and failure.provider == "news_a"
    assert "1 NEWS item(s) older than" in failure.message


def test_freshness_uses_publication_time_over_retrieval_time() -> None:
    snap = build(ok(SRC, item("republished", age=timedelta(hours=30), published=True)))
    assert snap.items == () and snap.failures[0].kind is ProviderErrorKind.STALE


def test_freshness_boundary_is_inclusive_and_windows_are_per_category() -> None:
    windows = AGE | {EvidenceCategory.WEATHER: timedelta(hours=1)}
    weather = item("wind", category=EvidenceCategory.WEATHER, age=timedelta(hours=2))
    exact = item("edge", age=timedelta(hours=24))
    snap = build_snapshot("evt-1", [ok(SRC, weather, exact)], NOW, max_age=windows)
    assert [i.extracted_fact for i in snap.items] == ["edge"]


def test_missing_freshness_window_is_an_error_not_a_silent_default() -> None:
    with pytest.raises(ValueError, match="no freshness window"):
        build_snapshot("evt-1", [ok(SRC, item())], NOW, max_age={})


def test_duplicates_across_providers_collapse_to_the_earliest_report() -> None:
    late = item("Starting QB is  QUESTIONABLE!", provider="news_b", age=timedelta(minutes=5))
    early = item(provider="news_a", age=timedelta(hours=3))
    snap = build(ok(SRC_B, late), ok(SRC, early))
    assert snap.items == (early,)
    other_kind = item(kind=ClaimKind.CONFIRMED_FACT)  # same words, different claim: kept apart
    assert len(build(ok(SRC, early, other_kind)).items) == 2


def test_inference_is_repointed_when_its_source_collapses() -> None:
    early = item(age=timedelta(hours=3))
    late = item("starting qb is questionable", provider="news_b", age=timedelta(hours=1))
    inference = item(
        "Passing offense likely reduced.",
        kind=ClaimKind.INFERENCE,
        derived_from=(late.evidence_id,),
    )
    snap = build(ok(SRC, early, late, inference))
    by_kind = {i.claim_kind: i for i in snap.items}
    assert len(snap.items) == 2
    assert by_kind[ClaimKind.INFERENCE].derived_from == (early.evidence_id,)


def test_snapshot_is_deterministic_and_input_order_independent() -> None:
    a, b = item("one"), item("two", provider="news_b")
    first = build(ok(SRC, a), ok(SRC_B, b))
    assert first == build(ok(SRC, a), ok(SRC_B, b))
    assert {i.evidence_id for i in build(ok(SRC_B, b), ok(SRC, a)).items} == {
        i.evidence_id for i in first.items
    }
