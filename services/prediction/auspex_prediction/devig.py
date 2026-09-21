"""Vig removal and cross-book consensus.

Only the proportional (multiplicative) method is implemented: each raw implied probability is
divided by the book's total. It is the simplest transparent method; Shin/power methods can be
added when calibration data shows they matter.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from statistics import median

from auspex_prediction.core import (
    ONE,
    InsufficientData,
    require_aware,
    require_probability,
)


@dataclass(frozen=True)
class DevigResult:
    fair_probabilities: dict[str, Decimal]
    overround: Decimal  # sum of raw implied probabilities minus 1; the book's margin
    method: str = "PROPORTIONAL"


@dataclass(frozen=True)
class BookQuote:
    """One book's raw implied probabilities for a complete, mutually exclusive outcome set."""

    book: str
    observed_at_utc: datetime
    implied_probabilities: Mapping[str, Decimal]


@dataclass(frozen=True)
class ConsensusResult:
    fair_probabilities: dict[str, Decimal]
    books_used: tuple[str, ...]
    method: str = "MEDIAN_OF_PROPORTIONAL_DEVIG"


def devig_proportional(implied_probabilities: Mapping[str, Decimal]) -> DevigResult:
    """Normalize a complete outcome set (e.g. HOME/AWAY, or HOME/DRAW/AWAY) to sum to 1.

    The caller must pass every outcome of the market; a partial set silently produces wrong
    probabilities, so fewer than two outcomes is rejected. A negative overround (raw sum < 1)
    signals stale or mismatched quotes and is rejected rather than normalized.
    """
    if len(implied_probabilities) < 2:
        raise ValueError("de-vig needs the complete outcome set (at least two outcomes)")
    raw = {
        k: require_probability(f"implied_probabilities[{k}]", v, open_interval=True)
        for k, v in implied_probabilities.items()
    }
    total = sum(raw.values(), Decimal(0))
    if total < ONE:
        raise ValueError(f"raw implied probabilities sum to {total} < 1; quotes stale or mismatched")
    return DevigResult({k: v / total for k, v in raw.items()}, overround=total - ONE)


def consensus_fair_probabilities(
    quotes: Sequence[BookQuote],
    *,
    as_of_utc: datetime,
    max_quote_age: timedelta,
    min_books: int = 2,
) -> ConsensusResult | InsufficientData:
    """Median of per-book de-vigged probabilities across all fresh books.

    Uses every fresh book rather than the most favorable one. Stale, future-dated, or
    outcome-mismatched quotes are excluded and named in the INSUFFICIENT_DATA reasons when too
    few books remain. Medians are renormalized so the consensus sums to 1.
    """
    require_aware("as_of_utc", as_of_utc)
    if min_books < 1:
        raise ValueError("min_books must be >= 1")
    if not quotes:
        return InsufficientData(("no external book quotes available",))

    outcomes = set(quotes[0].implied_probabilities)
    excluded: list[str] = []
    fresh: list[tuple[str, DevigResult]] = []
    for q in quotes:
        age = as_of_utc - require_aware("observed_at_utc", q.observed_at_utc)
        if age < timedelta(0):
            excluded.append(f"{q.book}: quote timestamp is after as_of_utc")
        elif age > max_quote_age:
            excluded.append(f"{q.book}: quote is stale ({age} old)")
        elif set(q.implied_probabilities) != outcomes:
            excluded.append(f"{q.book}: outcome set differs from {sorted(outcomes)}")
        else:
            fresh.append((q.book, devig_proportional(q.implied_probabilities)))

    if len(fresh) < min_books:
        return InsufficientData(
            (f"only {len(fresh)} usable book quote(s); {min_books} required", *excluded)
        )
    medians = {o: median(r.fair_probabilities[o] for _, r in fresh) for o in sorted(outcomes)}
    total = sum(medians.values(), Decimal(0))
    return ConsensusResult(
        fair_probabilities={o: m / total for o, m in medians.items()},
        books_used=tuple(book for book, _ in fresh),
    )
