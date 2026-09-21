"""Break-even probability, expected profit, and expected return for a single position.

``gross_payout_usd`` includes the returned stake (the amount received if the position wins).
Fees and slippage are explicit caller inputs; nothing is assumed about their size.
"""

from dataclasses import dataclass
from decimal import Decimal

from auspex_prediction.core import (
    HUNDRED,
    require_probability,
    require_usd,
)
from auspex_prediction.odds import SHARE_PAYOUT_USD


@dataclass(frozen=True)
class PositionCosts:
    stake_usd: Decimal
    gross_payout_usd: Decimal
    estimated_fees_usd: Decimal
    estimated_slippage_usd: Decimal

    def __post_init__(self) -> None:
        require_usd("stake_usd", self.stake_usd, positive=True)
        require_usd("gross_payout_usd", self.gross_payout_usd, positive=True)
        require_usd("estimated_fees_usd", self.estimated_fees_usd)
        require_usd("estimated_slippage_usd", self.estimated_slippage_usd)

    @property
    def total_cost_usd(self) -> Decimal:
        return self.stake_usd + self.estimated_fees_usd + self.estimated_slippage_usd


@dataclass(frozen=True)
class ExpectedValue:
    model_probability: Decimal
    break_even_probability: Decimal
    edge_probability_points: Decimal
    expected_profit_usd: Decimal
    expected_return_pct: Decimal


def gross_payout_usd_for_shares(stake_usd: Decimal, market_price_usd: Decimal) -> Decimal:
    """Gross payout of ``stake_usd`` spent on 1.00 USD binary shares at ``market_price_usd``.

    Assumes fractional shares; round to the venue's share increment before comparing to a quote.
    """
    stake = require_usd("stake_usd", stake_usd, positive=True)
    price = require_probability("market_price_usd", market_price_usd, open_interval=True)
    return stake / price * SHARE_PAYOUT_USD


def break_even_probability(costs: PositionCosts) -> Decimal:
    """Win probability at which expected profit is zero: total cost / gross payout.

    May exceed 1 when costs exceed the payout, meaning no probability breaks even.
    """
    return costs.total_cost_usd / costs.gross_payout_usd


def expected_profit_usd(model_probability: Decimal, costs: PositionCosts) -> Decimal:
    """``p * gross_payout - stake - fees - slippage``. Unrounded; round only for display."""
    p = require_probability("model_probability", model_probability)
    return p * costs.gross_payout_usd - costs.total_cost_usd


def expected_return_pct(model_probability: Decimal, costs: PositionCosts) -> Decimal:
    """Expected profit as a percent of ``stake_usd`` (fees/slippage are in the numerator)."""
    return expected_profit_usd(model_probability, costs) / costs.stake_usd * HUNDRED


def evaluate_position(model_probability: Decimal, costs: PositionCosts) -> ExpectedValue:
    p = require_probability("model_probability", model_probability)
    be = break_even_probability(costs)
    return ExpectedValue(
        model_probability=p,
        break_even_probability=be,
        edge_probability_points=(p - be) * HUNDRED,
        expected_profit_usd=expected_profit_usd(p, costs),
        expected_return_pct=expected_return_pct(p, costs),
    )
