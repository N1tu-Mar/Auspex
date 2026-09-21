from datetime import UTC, datetime, timedelta
from decimal import Decimal as D

import pytest
from auspex_prediction.core import InsufficientData
from auspex_prediction.devig import (
    BookQuote,
    ConsensusResult,
    consensus_fair_probabilities,
    devig_proportional,
)
from auspex_prediction.odds import implied_probability_from_american_odds as am

NOW = datetime(2026, 9, 21, 12, tzinfo=UTC)
FRESH = timedelta(minutes=30)


def quote(book: str, home: D, away: D, age_min: int = 5) -> BookQuote:
    return BookQuote(book, NOW - timedelta(minutes=age_min), {"HOME": home, "AWAY": away})


def test_devig_standard_minus_110_pair() -> None:
    r = devig_proportional({"HOME": am(-110), "AWAY": am(-110)})
    # 110/210 is not finite in base 10; 28-digit Decimal context leaves a last-digit residue.
    assert {k: v.quantize(D("1e-20")) for k, v in r.fair_probabilities.items()} == {
        "HOME": D("0.5"),
        "AWAY": D("0.5"),
    }
    assert r.overround.quantize(D("0.0001")) == D("0.0476")


def test_devig_sums_to_one_three_way() -> None:
    r = devig_proportional({"HOME": D("0.45"), "DRAW": D("0.30"), "AWAY": D("0.35")})
    assert sum(r.fair_probabilities.values()) == 1
    assert r.fair_probabilities["HOME"] == D("0.45") / D("1.10")


def test_devig_zero_overround_is_identity() -> None:
    r = devig_proportional({"YES": D("0.6"), "NO": D("0.4")})
    assert r.fair_probabilities == {"YES": D("0.6"), "NO": D("0.4")}
    assert r.overround == 0


def test_devig_rejects_single_outcome() -> None:
    with pytest.raises(ValueError, match="complete outcome set"):
        devig_proportional({"HOME": D("0.5")})


def test_devig_rejects_underround() -> None:
    with pytest.raises(ValueError, match="stale or mismatched"):
        devig_proportional({"HOME": D("0.4"), "AWAY": D("0.4")})


@pytest.mark.parametrize("bad", [D(0), D(1), 0.5])
def test_devig_rejects_bad_probability(bad: object) -> None:
    with pytest.raises((ValueError, TypeError)):
        devig_proportional({"HOME": bad, "AWAY": D("0.5")})  # type: ignore[dict-item]


def test_consensus_uses_median_not_best_price() -> None:
    quotes = [
        quote("a", D("0.55"), D("0.50")),
        quote("b", D("0.60"), D("0.45")),
        quote("c", D("0.70"), D("0.35")),  # outlier does not drive consensus
    ]
    r = consensus_fair_probabilities(quotes, as_of_utc=NOW, max_quote_age=FRESH)
    assert isinstance(r, ConsensusResult)
    assert r.books_used == ("a", "b", "c")
    assert sum(r.fair_probabilities.values()) == 1
    assert r.fair_probabilities["HOME"].quantize(D("0.0001")) == D("0.5714")


def test_consensus_excludes_stale_and_future_quotes() -> None:
    quotes = [
        quote("fresh1", D("0.52"), D("0.52")),
        quote("fresh2", D("0.52"), D("0.52")),
        quote("stale", D("0.9"), D("0.2"), age_min=120),
        quote("future", D("0.9"), D("0.2"), age_min=-5),
    ]
    r = consensus_fair_probabilities(quotes, as_of_utc=NOW, max_quote_age=FRESH)
    assert isinstance(r, ConsensusResult)
    assert r.books_used == ("fresh1", "fresh2")


def test_consensus_insufficient_books_lists_reasons() -> None:
    quotes = [quote("a", D("0.52"), D("0.52")), quote("old", D("0.52"), D("0.52"), age_min=99)]
    r = consensus_fair_probabilities(quotes, as_of_utc=NOW, max_quote_age=FRESH)
    assert isinstance(r, InsufficientData)
    assert "1 usable" in r.reasons[0]
    assert any("old: quote is stale" in reason for reason in r.reasons)


def test_consensus_excludes_mismatched_outcomes() -> None:
    odd = BookQuote("x", NOW, {"HOME": D("0.5"), "DRAW": D("0.3"), "AWAY": D("0.3")})
    r = consensus_fair_probabilities(
        [quote("a", D("0.52"), D("0.52")), odd], as_of_utc=NOW, max_quote_age=FRESH
    )
    assert isinstance(r, InsufficientData)
    assert any("outcome set differs" in reason for reason in r.reasons)


def test_consensus_empty() -> None:
    r = consensus_fair_probabilities([], as_of_utc=NOW, max_quote_age=FRESH)
    assert isinstance(r, InsufficientData)


def test_consensus_requires_aware_time() -> None:
    with pytest.raises(ValueError):
        consensus_fair_probabilities(
            [quote("a", D("0.5"), D("0.52"))],
            as_of_utc=datetime(2026, 9, 21),  # noqa: DTZ001 - deliberately naive
            max_quote_age=FRESH,
        )
